# 0003. The C++ reader: capsule's shape, when live operation needs it

- Status: Accepted; built 2026-11-15 (carried over from magnetometer-array's
  ADR-0002 of 2026-10-28)
- Date: 2026-11-15

## Context

Live navigation (`mipe`, roadmap M7) drains every device on one thread
through the same shape: a pure decoder, a reader thread behind a bounded
queue, `drain(sink)` on the caller's thread, and `replay(path, sink)`
through the same decoder. The capsule's host library has it; the board has
only the Python decoder. Replay from recordings does not need it: the
pipeline decodes in Python and the estimator reads `session.h5`.

## Decision

A C++ library `magarray::` under `cpp/`, consumable by `add_subdirectory`,
with the layers of the old ADR (built ahead of live operation since the
captures to test it against were there):

```
port → ByteSource → FrameParser → [EnvelopeDemux] → ScanDecoder → Board → drain(sink)
```

- `FrameParser` and `ScanDecoder` are pure: bytes in, frames and `Scan`s
  out, with counts of checksum, framing and structural errors; the sync
  pair is a parameter, so one parser serves board and center-board frames.
- `Board` owns the source and the decoders: a thread, a bounded queue,
  reconnection, `drain(sink)`, `wait_for`, status.
- `replay(path, sink)` reads `.bsr` (0002) and feeds the same decoder with
  the recorded arrivals.
- Events carry the host arrival (`steady_clock`) and the board's ticks; raw
  counts, no scale: the consumer applies calibration.
- Linux first; the serial port is the one platform-specific piece.

## Consequences

The Python decoder stays the reference; the C++ one is tested against the
same `tests/data` captures and produces the same scans (191 from the
2026-10-28 cut, 0 from the floating line). `FrameParser` and `StreamDecoder`
are pure; `Board` owns the thread and the queue; `open_serial` is the one
platform piece (termios, an exclusive flock, DTR and RTS low).

## Would change this

A need to read four boards at 85 % of the line's bandwidth in Python
turning out too slow for a live view: build it sooner.
