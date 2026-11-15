"""The LIS3MDL's output in physical units (datasheet DS9463, Table 2).

The board sends each sensor's raw output: signed 16-bit counts per axis, in the
sensor's own axes (docs/wire-protocol.md 4.1). Their size depends on the full
scale the firmware configured, which nothing on the wire reports.
"""

from __future__ import annotations

import numpy as np

COUNTS_PER_GAUSS = {4: 6842.0, 8: 3421.0, 12: 2281.0, 16: 1711.0}  # typical sensitivity, by full scale [gauss]
TESLA_PER_GAUSS = 1e-4

# The board's full scale, inferred rather than read, two ways (2026-11-08):
# - a 6×6 mm N42 magnet on the robot arm fits with 1.09 times its nominal
#   moment at ±4 gauss, and would need 2.2 times or more at any other setting;
# - the steady field the sensors' offsets leave is 44 µT, Earth-like, at ±4
#   gauss, and would be 87 µT or more at any other setting.
# The legacy tools ran their board at ±16 gauss. The firmware would settle it.
FULL_SCALE_GAUSS = 4


def counts_per_tesla(full_scale_gauss: int = FULL_SCALE_GAUSS) -> float:
    return COUNTS_PER_GAUSS[full_scale_gauss] / TESLA_PER_GAUSS


def to_tesla(counts, full_scale_gauss: int = FULL_SCALE_GAUSS) -> np.ndarray:
    """Counts of any shape to tesla, at the typical sensitivity: one count is 14.6 nT at ±4 gauss.
    Each sensor's own gain and offset are a calibration's (magarray.armfit)."""
    return np.asarray(counts, dtype=float) / counts_per_tesla(full_scale_gauss)
