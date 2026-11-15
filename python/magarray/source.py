"""Where scans come from: the serial port, receive-only, or a recording. Each runs in its own thread.

A scan's `received` is the host's steady clock in seconds (`time.monotonic()`), for the viewer; the
recording keeps the same clock in integer ns (docs/recording-format.md)."""

from __future__ import annotations

import copy
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .recording import Writer, now_ns, read, recording_path
from .wire import TICKS_PER_SECOND, DecoderStats, Scan, StreamDecoder

BAUD = 921600


@dataclass
class SourceStatus:
    description: str
    connected: bool = False
    bytes: int = 0
    error: str | None = None
    finished: bool = False


def read_recording(path: str | Path) -> list[tuple[float, bytes]]:
    """A recording as (arrival time [s], bytes) reads; an untimed legacy `.bin` gets nan."""
    rec = read(path)
    return [(t / 1e9 if rec.timed else float("nan"), data) for t, data in rec.records]


class _Source(threading.Thread):
    def __init__(self, description: str, framing: str) -> None:
        super().__init__(daemon=True)
        self._queue: queue.SimpleQueue[Scan] = queue.SimpleQueue()
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._decoder = StreamDecoder(framing)
        self.status = SourceStatus(description)

    def take(self) -> list[Scan]:
        """Every scan queued so far, oldest first. For one consumer thread."""
        out = []
        while True:
            try:
                out.append(self._queue.get_nowait())
            except queue.Empty:
                return out

    def stats(self) -> DecoderStats:
        with self._lock:
            return copy.deepcopy(self._decoder.stats)

    def stop(self) -> None:
        self._stop_event.set()

    def _decode(self, data: bytes, received: float) -> list[Scan]:
        with self._lock:
            return self._decoder.feed(data, received)


class SerialSource(_Source):
    """Reads a port, never writes to it. RTS is held deasserted, and DTR too unless `dtr`: the
    capsule streams only while DTR is asserted. Locks the port, so a second reader waits instead of
    splitting the bytes with the first. Reconnects by itself."""

    def __init__(
        self,
        port: str,
        framing: str = "auto",
        record: str | Path | None = None,
        dtr: bool = False,
        overwrite: bool = False,
        note: dict | None = None,
    ) -> None:
        super().__init__(port, framing)
        self._port = port
        self._dtr = dtr
        self._recorder = None
        if record:
            note = {"port": port, "baud": BAUD, "dtr": dtr} | (note or {})
            self._recorder = Writer(recording_path(record), note, overwrite)

    def run(self) -> None:
        import serial  # only needed for live data

        try:
            while not self._stop_event.is_set():
                try:
                    s = serial.Serial()
                    s.port, s.baudrate, s.timeout, s.exclusive = self._port, BAUD, 0.05, True
                    s.dtr, s.rts = self._dtr, False
                    s.open()
                except (serial.SerialException, OSError) as e:
                    busy = "exclusively lock" in str(e)
                    self.status.connected = False
                    self.status.error = "busy: another reader holds the port (a suspended one?)" if busy else str(e)
                    self._stop_event.wait(0.5)
                    continue
                self.status.connected, self.status.error = True, None
                with self._lock:
                    self._decoder.restart()
                try:
                    while not self._stop_event.is_set():
                        data = s.read(s.in_waiting or 1)  # returns as soon as anything has arrived
                        if not data:
                            continue
                        received_ns = now_ns()
                        self.status.bytes += len(data)
                        if self._recorder:
                            self._recorder.write(data, received_ns)
                        for scan in self._decode(data, received_ns / 1e9):
                            self._queue.put(scan)
                except (serial.SerialException, OSError) as e:
                    self.status.connected, self.status.error = False, str(e)
                finally:
                    s.close()
        finally:
            if self._recorder:
                self._recorder.close()
            self.status.connected, self.status.finished = False, True


class ReplaySource(_Source):
    """Plays a recording back at `speed` times real time, paced by the board's own time."""

    def __init__(self, path: str | Path, speed: float = 1.0, loop: bool = False, framing: str = "auto") -> None:
        super().__init__(str(path), framing)
        self._path, self._speed, self._loop = Path(path), speed, loop

    def run(self) -> None:
        scans: list[Scan] = []
        for received, data in read_recording(self._path):
            scans += self._decode(data, received)
            self.status.bytes += len(data)
        self.status.connected = True
        try:
            while not self._stop_event.is_set():
                self._play(scans)
                if not self._loop:
                    break
        finally:
            self.status.connected, self.status.finished = False, True

    def _play(self, scans: list[Scan]) -> None:
        if not scans:
            return
        start, elapsed, last = time.monotonic(), 0, scans[0].ticks
        for scan in scans:
            elapsed += (scan.ticks - last) & 0xFFFFFFFF
            last = scan.ticks
            due = start + elapsed / TICKS_PER_SECOND / self._speed
            if self._stop_event.wait(max(0.0, due - time.monotonic())):
                return
            self._queue.put(scan)
