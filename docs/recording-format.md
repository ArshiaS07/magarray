# Byte-stream recording (`.bsr`)

A port's bytes, exactly as each read returned them, each read with the
host's arrival time. One file per device per session. Written by `magarray
record` (and by the capsule's recorder, which shares the format); read by
`magarray.recording.read`, by `magarray view --file`, and by the pipeline's
`decode`.

Why this shape: a recording that keeps the reads, not just the bytes,
replays through a decoder exactly as the live stream did, and the arrival
times let the device's own clock be mapped onto the host's afterwards. The
header's two clocks make the file comparable with the arm's `.ecraw`, which
records the same pair.

## Layout

Little-endian throughout.

| Offset | Size | Field |
|---|---|---|
| 0 | 8 | magic `BSTREAM1` (the last character is the version) |
| 8 | 8 | int64: the host's steady clock at creation, ns (`CLOCK_MONOTONIC`; `std::chrono::steady_clock`) |
| 16 | 8 | int64: the host's system clock at creation, ns since 1970-01-01 UTC |
| 24 | 4 | u32: length of the note |
| 28 | note | UTF-8 JSON: free facts about the recording (`device`, `port`, `baud`, `dtr`, `recorder`); may be `{}` |
| 28 + note | … | records, until the end of the file |

Each record:

| Size | Field |
|---|---|
| 8 | int64: arrival time of the read, ns on the steady clock |
| 4 | u32: number of bytes |
| n | the bytes, as received |

A file that ends inside a record was cut short (the recorder was killed
mid-write); the reader keeps every complete record and reports `truncated`.

## Time

The arrival time is taken after the read returns, so it is an upper bound on
when the last byte of the read arrived; the lower envelope of arrival time
against device time gives the clock map (the minimum-delay estimator). The
steady clock's epoch is arbitrary (usually the boot); it is the same clock
in every recording made on this host during one boot. The system clock at
creation gives the calendar time: `system_ns_at_start + (arrival −
steady_ns_at_start)`.

## Legacy files

Before 2026-11-15 magnetometer-array wrote two files per recording: `.chunks`,
headerless records of `(f64 seconds, u32 length, bytes)` with
`time.monotonic()` seconds, and `.bin`, the bytes alone. `read` detects the
missing magic and returns the same `Recording`, with `legacy=True`; a `.bin`
is one untimed record. Nothing writes the old layouts.

## In Python

```python
from magarray.recording import Writer, read, now_ns
w = Writer("run.bsr", note={"device": "magarray", "port": port})
w.write(data, now_ns())       # per read
w.close()                     # removes the file if nothing was written
rec = read("run.bsr")         # .records: [(arrival_ns, bytes)], .note, .steady_ns_at_start, ...
```
