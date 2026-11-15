"""What one board has sent lately: history, repeats, peaks, noise, tare. No I/O, no GUI."""

from __future__ import annotations

import numpy as np

from .wire import TICKS_PER_SECOND, Scan

INT16_LIMIT = 32767


class BoardMonitor:
    """Keeps the last `history_s` of one board's scans and what can be read from them.

    A reading is *fresh* when its field differs from that sensor's previous
    one; the board polls at about twice the sensors' rate, so about half are
    repeats (wire protocol 4.1). Statistics use fresh readings only.
    """

    def __init__(self, sensor_ids: np.ndarray, history_s: float = 10.0, scan_hz: float = 80.0) -> None:
        self.sensor_ids = np.asarray(sensor_ids, dtype=np.uint8)
        n = len(self.sensor_ids)
        cap = int(history_s * scan_hz * 1.5) + 1
        self._t = np.full(cap, np.nan)  # board seconds
        self._field = np.zeros((cap, n, 3), dtype=np.int16)
        self._fresh = np.zeros((cap, n), dtype=bool)
        self._head = 0  # next slot
        self._count = 0
        self._last: np.ndarray | None = None
        self._ticks_last: int | None = None
        self._ticks_unwrapped = 0
        self.scans = 0
        self.mismatched = 0
        self.time_resets = 0
        self.peak_abs = np.zeros(n, dtype=np.int32)
        self.last_fresh_t = np.full(n, np.nan)
        self.tare: np.ndarray | None = None  # [n, 3] counts

    @property
    def n(self) -> int:
        return len(self.sensor_ids)

    def add(self, scan: Scan) -> None:
        if not np.array_equal(scan.sensor_ids, self.sensor_ids):
            self.mismatched += 1  # other sensors, or another order: not this board's layout
            return
        field = scan.field
        t = self._board_seconds(scan.ticks)
        fresh = np.ones(self.n, dtype=bool) if self._last is None else np.any(field != self._last, axis=1)
        self._last = field
        i = self._head
        self._t[i], self._field[i], self._fresh[i] = t, field, fresh
        self._head = (i + 1) % len(self._t)
        self._count = min(self._count + 1, len(self._t))
        self.scans += 1
        np.maximum(self.peak_abs, np.abs(field.astype(np.int32)).max(axis=1), out=self.peak_abs)
        self.last_fresh_t[fresh] = t

    def _board_seconds(self, ticks: int) -> float:
        if self._ticks_last is not None:
            step = (ticks - self._ticks_last) & 0xFFFFFFFF
            if step > 0x80000000:  # backwards, not a wrap: the board restarted
                self.time_resets += 1
                self._last = None
                step = 0
            self._ticks_unwrapped += step
        self._ticks_last = ticks
        return self._ticks_unwrapped / TICKS_PER_SECOND

    @property
    def now(self) -> float:
        """Board seconds of the newest scan."""
        return float(self._t[(self._head - 1) % len(self._t)]) if self._count else np.nan

    def window(self, seconds: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(t [k], field [k, n, 3], fresh [k, n]) of the last `seconds`, oldest first."""
        idx = (self._head - self._count + np.arange(self._count)) % len(self._t)
        t = self._t[idx]
        keep = t >= self.now - seconds
        idx = idx[keep]
        return self._t[idx], self._field[idx], self._fresh[idx]

    def latest(self) -> np.ndarray | None:
        return self._last

    def fresh_mean(self, seconds: float) -> np.ndarray:
        """[n, 3] mean of each sensor's fresh readings over the last `seconds`."""
        _, f, fresh = self.window(seconds)
        w = fresh[:, :, None].astype(float)
        with np.errstate(invalid="ignore", divide="ignore"):
            return (f * w).sum(0) / w.sum(0)

    def noise(self, seconds: float = 2.0) -> np.ndarray:
        """[n] RMS over the axes of each sensor's standard deviation (fresh readings, last `seconds`)."""
        _, f, fresh = self.window(seconds)
        out = np.full(self.n, np.nan)
        for s in range(self.n):
            v = f[fresh[:, s], s, :].astype(float)
            if len(v) >= 3:
                out[s] = np.sqrt(np.mean(v.var(axis=0, ddof=1)))
        return out

    def stale(self, limit_s: float = 0.5) -> np.ndarray:
        """[n] True where a sensor has had no fresh reading for `limit_s`."""
        with np.errstate(invalid="ignore"):
            return ~(self.now - self.last_fresh_t <= limit_s)

    def scan_rate(self, seconds: float = 2.0) -> float:
        t, _, _ = self.window(seconds)
        return (len(t) - 1) / (t[-1] - t[0]) if len(t) > 2 and t[-1] > t[0] else np.nan

    def fresh_rate(self, seconds: float = 2.0) -> float:
        """Mean fresh readings per second per sensor."""
        t, _, fresh = self.window(seconds)
        return fresh[1:].sum() / self.n / (t[-1] - t[0]) if len(t) > 2 and t[-1] > t[0] else np.nan

    def set_tare(self, seconds: float) -> None:
        self.tare = self.fresh_mean(seconds)

    def reset_peaks(self) -> None:
        self.peak_abs[:] = 0
