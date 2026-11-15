# magarray

The host side of the 5×5 LIS3MDL magnetometer board: what it sends
(`docs/wire-protocol.md`), a decoder, a recorder that keeps every read with
its arrival time (`docs/recording-format.md`), and a live viewer. Receive
only: nothing here writes to the board.

This repository knows the board and nothing else. Calibration, the robot arm
and navigation live in [mipe](../mipe), which depends on this one.

```
python/magarray/   wire (decoder), recording (.bsr read/write), source (port or replay, threaded),
                   monitor, view (Qt), cli
python/tests/      with small captures under tests/data, shared with the C++ tests
cpp/               the same in C++: wire, recording, Board (thread, queue, drain), replay; magarray_dump
docs/              wire-protocol, recording-format, decisions, slides
```

## Use

```sh
python/setup.sh                                  # once: a uv venv outside the exFAT mount, with Qt
python/magarray.sh view                          # the board's CP2102, or the only port; else --port
python/magarray.sh record recordings/<name> --seconds 900     # -> <name>.bsr; Ctrl+C (or Ctrl+Z) stops
python/magarray.sh record <name> --dtr --port /dev/serial/by-id/usb-STM…   # the capsule, until it records itself
python/magarray.sh info <name>.bsr               # bytes, reads, scans, errors, repeats, peak
python/magarray.sh view --file <name>.bsr --loop
```

A reader locks its port, so a second one waits ("busy") rather than
splitting the bytes. `record` never replaces a recording without
`--overwrite`, writes unbuffered, and removes a file that received nothing.
Without `--port` it picks the CP2102, or the only port; with two candidates
it asks.

Tests, from `python/`: `uv run pytest` (with `UV_PROJECT_ENVIRONMENT` as in
`setup.sh`).

## From C++

```cmake
add_subdirectory(<magarray>/cpp)          # or a submodule under external/
target_link_libraries(app PRIVATE magarray::magarray)
```

```cpp
magarray::BoardOptions o;                 // a reader thread, a bounded queue, reconnection
o.open = [] { return magarray::open_serial("/dev/ttyUSB1"); };
o.record = "session/raw/board0";          // tee every read to board0.bsr
magarray::Board board(o);
board.wait_for(100ms);
board.drain([](const magarray::Scan& s) { /* raw counts, the board's ticks, the host's arrival */ });
magarray::replay("board0.bsr", sink);     // the same decoder, the recorded arrivals
```

Build and test alone: `cmake -S cpp -B build/cpp && cmake --build build/cpp &&
ctest --test-dir build/cpp` (GoogleTest from the system). Linux; the serial
port is the one platform piece.

## Status

- Wire protocol: measured on one board through the center board; the
  firmware's settings remain inferred (`docs/wire-protocol.md`).
- Python decoder, recorder, replay, viewer: in use since October 2026.
- C++ library: decoder, recording, `Board`, replay, `magarray_dump`; tested on the
  same captures as the Python decoder, scan for scan (decision 0003).

## History

Replaces `magnetometer-array` (2026-10-28 to 2026-11-15), which also grew
the arm calibration and the path planner; those moved to `mipe`. Its
recordings are indexed there as sessions.

## Licence and the use of an AI assistant

MIT. Parts of this repository are written with Claude Code under the
author's direction and review; decisions are the author's and are recorded
in `docs/decisions/`.
