import unittest

import numpy as np

from magarray.monitor import BoardMonitor
from magarray.wire import Scan

IDS = np.arange(4, dtype=np.uint8)


def scan(ticks: int, field) -> Scan:
    return Scan(
        channel=2,
        board_id=1,
        ticks=ticks,
        sensor_ids=IDS,
        field=np.asarray(field, dtype=np.int16),
        w=np.zeros(len(IDS), dtype=np.int16),
    )


class BoardMonitorTest(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(1)

    def feed(self, m, k0, k1, hold=2):
        """Scans k0..k1-1, each sensor's value held for `hold` scans, as the board does."""
        value = None
        for k in range(k0, k1):
            if (k - k0) % hold == 0:
                value = self.rng.normal(0, 30, (4, 3)).round() + 1000
            m.add(scan(12 * k, value))

    def test_repeats_are_not_fresh(self):
        m = BoardMonitor(IDS)
        self.feed(m, 0, 160)
        _, _, fresh = m.window(10.0)
        self.assertAlmostEqual(fresh.mean(), 0.5, places=2)
        self.assertAlmostEqual(m.fresh_rate(1.0), 40.0, delta=2.0)
        self.assertAlmostEqual(m.scan_rate(1.0), 80.0, delta=0.5)

    def test_noise_uses_fresh_readings(self):
        m = BoardMonitor(IDS)
        self.feed(m, 0, 800)
        self.assertTrue(np.all(np.abs(m.noise(5.0) - 30) < 4))

    def test_stale_sensor(self):
        m = BoardMonitor(IDS)
        self.feed(m, 0, 40)
        stuck = m.latest().copy()
        for k in range(40, 120):
            f = self.rng.normal(0, 30, (4, 3)).round() + 1000
            f[3] = stuck[3]  # sensor 3 stops changing
            m.add(scan(12 * k, f))
        np.testing.assert_array_equal(m.stale(0.5), [False, False, False, True])

    def test_tare_and_peaks(self):
        m = BoardMonitor(IDS)
        self.feed(m, 0, 400)
        m.set_tare(2.0)
        self.assertTrue(np.all(np.abs(m.tare - 1000) < 10))
        self.assertGreater(m.peak_abs.min(), 1000)
        m.reset_peaks()
        self.assertEqual(m.peak_abs.max(), 0)

    def test_board_restart(self):
        m = BoardMonitor(IDS)
        self.feed(m, 1000, 1010)
        m.add(scan(5, np.zeros((4, 3))))
        self.assertEqual(m.time_resets, 1)

    def test_other_sensors_are_not_mixed_in(self):
        m = BoardMonitor(IDS)
        m.add(Scan(2, 1, 0, np.arange(3, dtype=np.uint8), np.zeros((3, 3), np.int16), np.zeros(3, np.int16)))
        self.assertEqual((m.scans, m.mismatched), (0, 1))


if __name__ == "__main__":
    unittest.main()
