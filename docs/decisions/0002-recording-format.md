# 0002. One byte-stream recording format, with a header

- Status: Accepted
- Date: 2026-11-15
- Supersedes the two-file recording of `magnetometer-array` (`.bin` and
  `.chunks`).

## Context

A recording must replay through the decoder exactly as the live stream did,
and must let the board's clock be mapped onto the host's afterwards. The old
`.chunks` did that with `(f64 seconds, u32, bytes)` records but had no magic,
no version and no record of the host's clocks at start, and a `.bin` copy of
the bytes beside it duplicated the data. The capsule's recorder keeps bytes
only, so its clock cannot be mapped offline; the arm's `.ecraw` records a
header with the steady and system clocks and `int64` ns arrivals.

## Decision

`docs/recording-format.md`: one file, `.bsr`; a header with magic, version,
the steady and system clocks at creation and a JSON note; records of
`(int64 arrival ns, u32 length, bytes)`. The same format is offered to the
capsule's recorder, so a session's two byte-stream devices and its arm share
one clock convention. `read` keeps reading the legacy layouts; nothing
writes them.

## Consequences

- One file per device per session; the bytes alone are `Recording.payload()`.
- The pipeline's `decode` reads the board's and the capsule's recordings
  with one function.
- The capsule's repository implements the writer and extends its replay
  (`mipe/docs/devices.md`).

## Would change this

A device that sends frames with their own timestamps at a rate where per-read
arrivals add nothing: it may record frames as the arm does; the header
convention stays.
