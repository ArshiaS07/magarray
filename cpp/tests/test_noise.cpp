// The noise model: the same cases as python/tests/test_noise.py.
#include <gtest/gtest.h>

#include "magarray/noise.hpp"

using namespace magarray;

TEST(NoiseModel, TheDatasheetsFigures) {
    constexpr NoiseModel m = NoiseModel::lis3mdl_datasheet();
    EXPECT_DOUBLE_EQ(m.sigma()[0], 3.2e-7);  // 3.2 mgauss
    EXPECT_DOUBLE_EQ(m.sigma()[1], 3.2e-7);
    EXPECT_DOUBLE_EQ(m.sigma()[2], 4.1e-7);
}

TEST(NoiseModel, AMeasuredSigmaHandedToIt) {
    constexpr NoiseModel m({6.1e-7, 6.2e-7, 6.3e-7});
    EXPECT_EQ(m.sigma()[1], 6.2e-7);
}

TEST(NoiseModel, TheCovarianceIsDiagonal) {
    constexpr Covariance3 c = NoiseModel({1e-7, 2e-7, 3e-7}).covariance();
    for (int i = 0; i < 3; ++i)
        for (int j = 0; j < 3; ++j)
            if (i != j) EXPECT_EQ(c[static_cast<std::size_t>(i)][static_cast<std::size_t>(j)], 0.0);
    EXPECT_DOUBLE_EQ(c[0][0], 1e-14);
    EXPECT_DOUBLE_EQ(c[1][1], 4e-14);
    EXPECT_DOUBLE_EQ(c[2][2], 9e-14);
}
