"""The noise model: the same cases as cpp/tests/test_noise.cpp."""

import unittest

import numpy as np

from magarray.noise import NoiseModel


class NoiseModelTest(unittest.TestCase):
    def test_the_datasheets_figures(self):
        self.assertEqual(NoiseModel.lis3mdl_datasheet().sigma_T, (3.2e-7, 3.2e-7, 4.1e-7))

    def test_a_measured_sigma_handed_to_it(self):
        self.assertEqual(NoiseModel((6.1e-7, 6.2e-7, 6.3e-7)).sigma_T[1], 6.2e-7)

    def test_the_covariance_is_diagonal(self):
        c = NoiseModel((1e-7, 2e-7, 3e-7)).covariance()
        np.testing.assert_allclose(c, np.diag([1e-14, 4e-14, 9e-14]), rtol=1e-12, atol=0)


if __name__ == "__main__":
    unittest.main()
