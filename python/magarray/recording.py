"""Byte-stream recordings: every read from a port, with its arrival time, in one file.

The format is docs/recording-format.md: a header (magic, the host's steady and system clocks
at start, a JSON note), then records of (int64 arrival ns on the steady clock, u32 length,
the bytes). The same bytes a live decoder saw, in the same reads, so a recording decodes
exactly as the live stream did and the arrival times can be mapped to the device's clock
afterwards. Files written before 2026-11-15 (`.chunks`: f64 seconds, u32, bytes, no header;
`.bin`: bytes only) still read.
"""

from __future__ import annotations

import json
import struct
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

MAGIC = b"BSTREAM1"
_HEADER = struct.Struct("<8sqqI")  # magic, steady ns, system ns, length of the note
_RECORD = struct.Struct("<qI")  # arrival ns, length
_LEGACY_RECORD = struct.Struct("<dI")  # arrival s, length
SUFFIX = ".bsr"


def recording_path(base: str | Path) -> Path:
    """`<base>.bsr`, unless the suffix is already there."""
    base = Path(base)
    return base if base.suffix == SUFFIX else base.with_name(base.name + SUFFIX)


def now_ns() -> int:
    """The host's steady clock in ns: CLOCK_MONOTONIC, the clock C++'s steady_clock reads on Linux."""
    return time.monotonic_ns()


@dataclass(frozen=True)
class Recording:
    path: Path
    records: list[tuple[int, bytes]]  # (arrival ns, bytes), in order; arrival 0 when the file had no times
    note: dict = field(default_factory=dict)
    steady_ns_at_start: int | None = None
    system_ns_at_start: int | None = None
    timed: bool = True  # False for a bytes-only legacy file
    legacy: bool = False
    truncated: bool = False  # the last record was cut short: the recorder stopped mid-write

    def payload(self) -> bytes:
        """The stream as one byte string."""
        return b"".join(data for _, data in self.records)


class Writer:
    """Writes a recording as reads arrive. Refuses an existing file unless `overwrite`; unbuffered,
    so what has arrived is on disk even if the process is killed; a file that received nothing is
    removed on close."""

    def __init__(self, path: str | Path, note: Mapping[str, object] | None = None, overwrite: bool = False) -> None:
        self.path = Path(path)
        if self.path.exists() and not overwrite:
            raise FileExistsError(f"already recorded: {self.path}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(dict(note or {}), separators=(",", ":")).encode()
        # Held open across reads and unbuffered: what has arrived is on disk even if the process dies.
        self._file = open(self.path, "wb", buffering=0)  # noqa: SIM115
        self._file.write(_HEADER.pack(MAGIC, now_ns(), time.time_ns(), len(text)) + text)
        self.written = 0  # payload bytes

    def write(self, data: bytes, arrival_ns: int) -> None:
        self._file.write(_RECORD.pack(arrival_ns, len(data)) + data)
        self.written += len(data)

    def close(self) -> None:
        self._file.close()
        if not self.written:
            self.path.unlink(missing_ok=True)


def read(path: str | Path) -> Recording:
    """A recording, of either layout; a `.bin` is one untimed record."""
    path = Path(path)
    raw = path.read_bytes()
    if raw[:8] == MAGIC:
        _, steady, system, n = _HEADER.unpack_from(raw)
        note = json.loads(raw[_HEADER.size : _HEADER.size + n] or b"{}")
        records, truncated = _records(raw, _HEADER.size + n, _RECORD, lambda t: int(t))
        return Recording(path, records, note, steady, system, truncated=truncated)
    if path.suffix == ".bin":
        return Recording(path, [(0, raw)], timed=False, legacy=True)
    records, truncated = _records(raw, 0, _LEGACY_RECORD, lambda t: round(t * 1e9))
    return Recording(path, records, legacy=True, truncated=truncated)


def _records(raw: bytes, i: int, layout: struct.Struct, to_ns) -> tuple[list[tuple[int, bytes]], bool]:
    out: list[tuple[int, bytes]] = []
    while i + layout.size <= len(raw):
        t, n = layout.unpack_from(raw, i)
        if i + layout.size + n > len(raw):
            return out, True
        out.append((to_ns(t), raw[i + layout.size : i + layout.size + n]))
        i += layout.size + n
    return out, i != len(raw)
