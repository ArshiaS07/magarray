"""magarray: the host side of the 5×5 LIS3MDL magnetometer board.

`wire` decodes the board's stream (docs/wire-protocol.md); `recording` reads and writes
byte-stream recordings with arrival times (docs/recording-format.md); `source` reads a port or
a recording in a thread and queues scans; `monitor` and `view` show them. Everything is
receive-only: nothing here writes to the board.
"""

__version__ = "0.2.0"
