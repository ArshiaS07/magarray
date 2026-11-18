/// @file noise.hpp
/// White-noise model of the board's magnetometers: one new sample's standard deviation per axis
/// in, its covariance out. A repeated sample (Scan::repeated) is not a new measurement and has no
/// noise of its own. Mirrors python/magarray/noise.py.
#ifndef MAGARRAY_NOISE_HPP
#define MAGARRAY_NOISE_HPP

#include <array>
#include <cstddef>

namespace magarray {

/// Covariance of one sample's three axes, row by row, T².
using Covariance3 = std::array<std::array<double, 3>, 3>;

class NoiseModel {
public:
    /// The LIS3MDL in its ultra-high-performance mode (datasheet DS9463 Rev 7, Table 2): rms noise
    /// 3.2 mgauss on x and y, 4.1 mgauss on z. Quoted at ±12 gauss and taken at every full scale;
    /// the board's mode is not reported, so the scatter measured at rest is the better figure when
    /// there is one (the constructor).
    static constexpr NoiseModel lis3mdl_datasheet() noexcept { return NoiseModel{{3.2e-7, 3.2e-7, 4.1e-7}}; }

    /// @param sigma_T one new sample's standard deviation per axis, T: measured at rest, or the
    ///        datasheet's.
    constexpr explicit NoiseModel(std::array<double, 3> sigma_T) noexcept : sigma_{sigma_T} {}

    [[nodiscard]] constexpr const std::array<double, 3>& sigma() const noexcept { return sigma_; }

    /// The covariance of one new sample: the axes taken as uncorrelated, so diagonal.
    [[nodiscard]] constexpr Covariance3 covariance() const noexcept {
        Covariance3 c{};
        for (std::size_t i = 0; i < 3; ++i) c[i][i] = sigma_[i] * sigma_[i];
        return c;
    }

private:
    std::array<double, 3> sigma_;
};

}  // namespace magarray

#endif  // MAGARRAY_NOISE_HPP
