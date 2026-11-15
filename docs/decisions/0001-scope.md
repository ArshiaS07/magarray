# 0001. Scope: the board's host side, and nothing else

- Status: Accepted
- Date: 2026-11-15

## Context

`magnetometer-array` began as the board's reader and grew the arm-magnet
calibration, the path planner, the board's geometry file and the calibration
format, because they were needed and nowhere else existed. They know the
robot and the magnet; the board does not. A thesis repository, `mipe`, now
exists for them, and it depends on device repositories that know only their
device (its decision 0008).

## Decision

This repository holds **what the board sends and how to receive it**: the
wire protocol, the decoder, the recording format and its reader and writer,
the threaded port and replay sources, the monitor and the viewer, and later
the C++ reader. It holds no calibration, no geometry beyond the numbering
the protocol implies, no robot, no navigation types, and no dependency on
`mipe`. The firmware is used as it is (unchanged from the old repository's
first decision); the reader never writes to the board, and holds DTR and RTS
low on the board's port.

Everything else left for `mipe`: `armfit`, `path`, `layout`, `dipole`,
`offline`, the board file, the calibration format, the recordings (indexed
there as sessions), the ADRs 0005–0008 and the findings.

## Consequences

- The package is small and its tests run from byte strings and small
  captures in `tests/data`.
- The old repository stays as it is, as history, until its recordings have
  moved.

## Would change this

Another device of the same family (a 7×7 board, a direct connection) is in
scope; another kind of device is a repository of its own.
