"""magarray: view, record, info. Nothing here ever writes to the board."""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

import numpy as np

from . import __version__
from .recording import MAGIC, SUFFIX, read, recording_path
from .source import SerialSource
from .wire import TICKS_PER_SECOND, StreamDecoder


def default_port(by_id: Path = Path("/dev/serial/by-id")) -> str:
    """The board's CP2102 when there is one, else the only port. Anything else (a phone, two boards) needs --port."""
    found = sorted(by_id.glob("*"))
    boards = [q for q in found if "CP210" in q.name]
    pick = boards if len(boards) == 1 else found if len(found) == 1 else []
    if not pick:
        sys.exit(f"which port? pass --port, one of: {', '.join(map(str, found)) or f'(nothing in {by_id})'}")
    print(f"port: {pick[0]}", file=sys.stderr)
    return str(pick[0])


def cmd_view(a: argparse.Namespace) -> int:
    from .view import run  # Qt only when needed

    port = None if a.file else (a.port or default_port())
    try:
        return run(port, a.file, a.speed, a.loop, a.record, a.saturation, a.screenshot, a.screenshot_after)
    except FileExistsError as e:
        sys.exit(f"{e}: pick another name")


def _interrupt(signum, frame):
    raise KeyboardInterrupt


def cmd_record(a: argparse.Namespace) -> int:
    port = a.port or default_port()
    out = recording_path(a.base)
    try:
        src = SerialSource(
            port,
            record=out,
            dtr=a.dtr,
            overwrite=a.overwrite,
            note={"device": "magarray" if not a.dtr else "capsule", "recorder": f"magarray {__version__}"},
        )
    except FileExistsError as e:
        sys.exit(f"{e}: pick another name, or pass --overwrite")
    # Ctrl+Z would suspend the recorder with the port still held and nothing more recorded; stop instead.
    for sig in (signal.SIGTSTP, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, _interrupt)
    print(f"recording {port} -> {out} for up to {a.seconds:g} s; Ctrl+C stops", file=sys.stderr)
    src.start()
    t0 = time.monotonic()
    scans = 0
    try:
        while time.monotonic() < t0 + a.seconds and not src.status.finished:
            time.sleep(0.5)
            scans += len(src.take())
            st = src.status
            waiting = "" if st.connected else f"  not reading: {st.error or 'opening'}"
            print(
                f"\r{time.monotonic() - t0:5.0f} s  {st.bytes} B  {scans} scans{waiting}\033[K",
                end="",
                flush=True,
                file=sys.stderr,
            )
    except KeyboardInterrupt:
        pass
    for sig in (signal.SIGINT, signal.SIGTSTP, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, signal.SIG_IGN)  # a second Ctrl+C would cut the file short
    src.stop()
    src.join(timeout=2.0)
    scans += len(src.take())
    seconds, received = time.monotonic() - t0, src.status.bytes
    print(
        f"\n{seconds:.0f} s, {received} B, {scans} scans ({scans / seconds:.0f}/s)"
        + (f" -> {out}" if received else ", no file written"),
        file=sys.stderr,
    )
    if not received or not (scans or a.dtr):  # the capsule's frames are not decoded here
        why = f"nothing arrived from {port}" if not received else "bytes, but no board scans: is it the board's port?"
        print(why + (f" ({src.status.error})" if src.status.error else ""), file=sys.stderr)
        return 1
    return 0


def cmd_info(a: argparse.Namespace) -> int:
    rec = read(a.file)
    dec = StreamDecoder()
    boards: dict = {}  # key -> ([ticks], [field])
    for arrival_ns, data in rec.records:
        for scan in dec.feed(data, arrival_ns / 1e9):
            ticks, fields = boards.setdefault(scan.key, ([], []))
            ticks.append(scan.ticks), fields.append(scan.field)
    s = dec.stats
    layout = "legacy layout" if rec.legacy else f"{MAGIC.decode()}, note {rec.note}"
    span = (
        f"{(rec.records[-1][0] - rec.records[0][0]) / 1e9:.1f} s of arrivals"
        if rec.timed and rec.records
        else "no times"
    )
    print(
        f"{a.file}: {len(rec.payload())} B in {len(rec.records)} reads ({layout}; {span}"
        f"{'; cut short' if rec.truncated else ''}); framing {s.framing}; scans {s.scans}; checksum errors "
        f"{s.checksum_errors}; oversize {s.oversize}; malformed {s.malformed}; unknown types {s.unknown_types}; "
        f"skipped {s.skipped_bytes} B"
    )
    for key, (ticks, fields) in boards.items():
        f = np.array(fields)  # [k, n, 3]
        steps, counts = np.unique(np.diff(np.array(ticks, dtype=np.int64)) & 0xFFFFFFFF, return_counts=True)
        repeated = np.all(f[1:] == f[:-1], axis=2)
        board_span = (sum(int(x) * int(c) for x, c in zip(steps, counts, strict=True))) / TICKS_PER_SECOND
        print(
            f"  board {key[1]} channel {key[0]}: {len(f)} scans of {f.shape[1]} sensors over {board_span:.1f} s "
            f"board time; tick steps {dict(zip(steps.tolist(), counts.tolist(), strict=True))}; "
            f"repeats {100 * repeated.mean():.1f} %; "
            f"peak |count| {int(np.abs(f.astype(np.int32)).max())}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="magarray", description=__doc__)
    p.add_argument("--version", action="version", version=f"magarray {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("view", help="live grid and time plot, from the port or a recording")
    v.add_argument("--port", help="default: the CP2102 in /dev/serial/by-id, or the only port there")
    v.add_argument("--file", help="a recording (.bsr, or a legacy .chunks / .bin) instead of the port")
    v.add_argument("--speed", type=float, default=1.0, help="replay speed")
    v.add_argument("--loop", action="store_true", help="replay over and over")
    v.add_argument("--record", metavar="BASE", help=f"also record the live stream to BASE{SUFFIX}")
    v.add_argument("--saturation", type=int, default=32000, help="|count| flagged as saturated (default 32000)")
    v.add_argument("--screenshot", metavar="PNG", help="save the window after --screenshot-after s, then quit")
    v.add_argument("--screenshot-after", type=float, default=5.0)
    v.set_defaults(fn=cmd_view)

    r = sub.add_parser("record", help=f"record the port to BASE{SUFFIX} (docs/recording-format.md)")
    r.add_argument("base")
    r.add_argument("--port", help="default: the CP2102 in /dev/serial/by-id, or the only port there")
    r.add_argument("--seconds", type=float, default=60.0, help="stops sooner on Ctrl+C (or Ctrl+Z)")
    r.add_argument("--overwrite", action="store_true", help=f"replace BASE{SUFFIX} if it exists")
    r.add_argument(
        "--dtr",
        action="store_true",
        help="assert DTR: the capsule streams only then (the board's port is read with it low)",
    )
    r.set_defaults(fn=cmd_record)

    i = sub.add_parser("info", help="summarise a recording")
    i.add_argument("file")
    i.set_defaults(fn=cmd_info)

    a = p.parse_args(argv)
    return a.fn(a)
