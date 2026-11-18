"""White-noise model of the board's magnetometers: one new sample's standard deviation per axis
in, its covariance out. A repeated sample (Scan.repeated) is not a new measurement and has no
noise of its own. Mirrors cpp/include/magarray/noise.hpp."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class NoiseModel:
    """One new sample's standard deviation per axis, T: measured at rest, or the datasheet's."""

    sigma_T: tuple[float, float, float]

    @classmethod
    def lis3mdl_datasheet(cls) -> NoiseModel:
        """The LIS3MDL in its ultra-high-performance mode (datasheet DS9463 Rev 7, Table 2): rms
        noise 3.2 mgauss on x and y, 4.1 mgauss on z. Quoted at ±12 gauss and taken at every full
        scale; the board's mode is not reported, so the scatter measured at rest is the better
        figure when there is one."""
        return cls((3.2e-7, 3.2e-7, 4.1e-7))

    def covariance(self) -> np.ndarray:
        """[3, 3] T²: the axes taken as uncorrelated, so diagonal."""
        return np.diag(np.square(np.asarray(self.sigma_T, dtype=float)))
