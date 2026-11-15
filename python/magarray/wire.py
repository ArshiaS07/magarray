"""The board's wire protocol (docs/wire-protocol.md): bytes in, scans out. No I/O."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

BOARD_SYNC = b"\xfa\x70"
CENTER_SYNC = b"\xad\x69"
SCAN_TYPE = 0x54  # board frame: one scan of the array
WRAPPED_TYPE = 0xAA  # center-board frame: one whole board frame
RECORD_SIZE = 9  # sensor id, x, y, z, w
MAX_PAYLOAD = 4 + RECORD_SIZE * 256 + 8  # a scan of 256 sensors, wrapped: anything longer is a false sync
TICKS_PER_SECOND = 960.0  # board time, measured on the bench (wire protocol 4.1)


@dataclass(frozen=True)
class Frame:
    type: int
    id: int
    payload: bytes


@dataclass(frozen=True)
class Scan:
    """One scan of one board, as on the wire."""

    channel: int | None  # center-board channel; None when the board is read directly
    board_id: int
    ticks: int  # board time, u32 as sent
    sensor_ids: np.ndarray  # uint8 [n]
    field: np.ndarray  # int16 [n, 3], raw counts, sensor axes (lis3mdl.to_tesla: 14.6 nT per count at ±4 gauss)
    w: np.ndarray  # int16 [n], not interpreted (−0.107·x on this firmware)
    received: float = math.nan  # host time.monotonic() of the read that completed it

    @property
    def key(self) -> tuple[int | None, int]:
        return (self.channel, self.board_id)


def checksum(body: bytes | bytearray | memoryview) -> int:
    return sum(body) & 0xFFFF


def encode_frame(sync: bytes, type_: int, id_: int, payload: bytes) -> bytes:
    """The inverse of FrameParser, for tests and simulation."""
    body = bytes([type_, id_]) + len(payload).to_bytes(2, "little") + payload
    return sync + body + checksum(body).to_bytes(2, "little")


class FrameParser:
    """Frames with one sync pair from a byte stream, fed in pieces of any size.

    Joins a stream midway; after a false sync (bad checksum, impossible
    length) it resumes one byte later, so a real frame starting inside a
    rejected one is still found.
    """

    def __init__(self, sync: bytes, max_payload: int = MAX_PAYLOAD) -> None:
        self._sync = sync
        self._max = max_payload
        self._buf = bytearray()
        self.frames = 0
        self.checksum_errors = 0
        self.oversize = 0
        self.skipped = 0  # bytes that were not part of any frame

    def feed(self, data: bytes) -> list[Frame]:
        buf = self._buf
        buf += data
        out: list[Frame] = []
        while True:
            i = buf.find(self._sync)
            if i < 0:
                keep = 1 if buf[-1:] == self._sync[:1] else 0  # may be the start of a sync
                self.skipped += len(buf) - keep
                del buf[: len(buf) - keep]
                break
            if i:
                self.skipped += i
                del buf[:i]
            if len(buf) < 6:
                break
            length = buf[4] | buf[5] << 8
            if length > self._max:
                self.oversize += 1
                self.skipped += 1
                del buf[:1]
                continue
            end = 8 + length
            if len(buf) < end:
                break
            if checksum(memoryview(buf)[2 : end - 2]) != (buf[end - 2] | buf[end - 1] << 8):
                self.checksum_errors += 1
                self.skipped += 1
                del buf[:1]
                continue
            out.append(Frame(buf[2], buf[3], bytes(buf[6 : end - 2])))
            self.frames += 1
            del buf[:end]
        return out

    def reset(self) -> None:
        self._buf.clear()


def decode_scan(frame: Frame, channel: int | None, received: float = math.nan) -> Scan | None:
    """A scan from a board frame of SCAN_TYPE; None if its payload is malformed."""
    p = frame.payload
    if len(p) < 4 or (len(p) - 4) % RECORD_SIZE:
        return None
    rec = np.frombuffer(p, dtype=np.uint8, offset=4).reshape(-1, RECORD_SIZE)
    ids = rec[:, 0].copy()
    if len(np.unique(ids)) != len(ids):
        return None
    values = rec[:, 1:].copy().view("<i2")  # [n, 4]: x, y, z, w
    return Scan(
        channel=channel,
        board_id=frame.id,
        ticks=int.from_bytes(p[:4], "little"),
        sensor_ids=ids,
        field=values[:, :3].astype(np.int16),
        w=values[:, 3].astype(np.int16),
        received=received,
    )


@dataclass
class DecoderStats:
    framing: str = "auto"
    scans: int = 0
    checksum_errors: int = 0
    oversize: int = 0
    malformed: int = 0
    unknown_types: int = 0
    skipped_bytes: int = 0
    per_board: dict[tuple[int | None, int], int] = field(default_factory=dict)


class StreamDecoder:
    """Scans from a board's stream, direct or through the center board.

    framing="auto" settles on "center" as soon as a center-board frame is
    valid, or on "direct" after a few board frames and no center-board frame:
    a center stream also contains valid board frames, inside its own. Scans
    decoded before it settles are dropped.
    """

    _DIRECT_AFTER = 4

    def __init__(self, framing: str = "auto") -> None:
        if framing not in ("auto", "center", "direct"):
            raise ValueError(f"framing: {framing!r}")
        self.stats = DecoderStats(framing=framing)
        self._center = FrameParser(CENTER_SYNC)
        self._direct = FrameParser(BOARD_SYNC)
        self._inner: dict[int, FrameParser] = {}

    @property
    def framing(self) -> str:
        return self.stats.framing

    def feed(self, data: bytes, received: float = math.nan) -> list[Scan]:
        mode = self.stats.framing
        scans: list[Scan] = []
        if mode in ("auto", "center"):
            for f in self._center.feed(data):
                if mode == "auto":
                    mode = self.stats.framing = "center"
                if f.type != WRAPPED_TYPE:
                    self.stats.unknown_types += 1
                    continue
                inner = self._inner.setdefault(f.id, FrameParser(BOARD_SYNC))
                for g in inner.feed(f.payload):
                    self._add(g, f.id, received, scans)
        if mode in ("auto", "direct"):
            frames = self._direct.feed(data)
            if mode == "auto" and self._direct.frames >= self._DIRECT_AFTER and self._center.frames == 0:
                mode = self.stats.framing = "direct"
            if mode == "direct":
                for g in frames:
                    self._add(g, None, received, scans)
        self._update_counters()
        return scans

    def restart(self) -> None:
        """Drops partial frames, e.g. after a reconnect; the framing and the counts are kept."""
        for p in (self._center, self._direct, *self._inner.values()):
            p.reset()

    def _add(self, frame: Frame, channel: int | None, received: float, out: list[Scan]) -> None:
        if frame.type != SCAN_TYPE:
            self.stats.unknown_types += 1
            return
        scan = decode_scan(frame, channel, received)
        if scan is None:
            self.stats.malformed += 1
            return
        self.stats.scans += 1
        self.stats.per_board[scan.key] = self.stats.per_board.get(scan.key, 0) + 1
        out.append(scan)

    def _update_counters(self) -> None:
        mode = self.stats.framing
        parsers = [self._center, *self._inner.values()] if mode == "center" else [self._direct]
        if mode == "auto":
            parsers = [self._center, self._direct]
        self.stats.checksum_errors = sum(p.checksum_errors for p in parsers)
        self.stats.oversize = sum(p.oversize for p in parsers)
        outer = self._center if mode in ("auto", "center") else self._direct
        self.stats.skipped_bytes = outer.skipped
