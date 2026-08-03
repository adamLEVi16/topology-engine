#include "perturbed_map.hpp"

#include <cmath>
#include <cstdint>
#include <stdexcept>

namespace {

std::uint32_t hash_u32(std::uint32_t x) {
    x ^= x >> 16; x *= 0x7feb352dU;
    x ^= x >> 15; x *= 0x846ca68bU;
    x ^= x >> 16;
    return x;
}

// Deterministic value in [-0.5, 0.5) at an integer lattice point.
double lattice(int ix, int iy, unsigned seed) {
    const auto h = hash_u32(static_cast<std::uint32_t>(ix) * 0x27d4eb2fu ^
                            static_cast<std::uint32_t>(iy) * 0x165667b1u ^ seed);
    return h * (1.0 / 4294967296.0) - 0.5;
}

}  // namespace

PerturbedMap::PerturbedMap(const Dem& base, double amplitude, double wavelength,
                           double aspect, unsigned seed)
    : base_(base), amplitude_(amplitude), seed_(seed) {
    if (wavelength <= 0.0) throw std::invalid_argument("error wavelength must be > 0");
    if (aspect <= 0.0) throw std::invalid_argument("error aspect must be > 0");

    // Keep the geometric mean of the two wavelengths fixed as aspect varies, so
    // the isotropy sweep changes the shape of the error features without also
    // changing their overall size.
    const double root = std::sqrt(aspect);
    lambda_x_ = wavelength * root;
    lambda_y_ = wavelength / root;

    scale_ = 1.0;
    if (amplitude > 0.0) calibrate_amplitude(amplitude);
}

void PerturbedMap::calibrate_amplitude(double target_rms) {
    // Single-octave smooth noise has an awkward analytic variance, so measure it
    // once on a coarse sweep and solve for the scale. This makes the amplitude
    // parameter mean exactly what it says: RMS metres of vertical error.
    double sum_sq = 0.0;
    int n = 0;
    const double step_x = std::max(base_.extent_x() / 180.0, 1e-6);
    const double step_y = std::max(base_.extent_y() / 180.0, 1e-6);
    for (double y = 0.0; y <= base_.extent_y(); y += step_y) {
        for (double x = 0.0; x <= base_.extent_x(); x += step_x) {
            const double v = error_field(x, y, nullptr);
            sum_sq += v * v;
            ++n;
        }
    }
    const double rms = (n > 0) ? std::sqrt(sum_sq / n) : 0.0;
    scale_ = (rms > 1e-12) ? target_rms / rms : 0.0;
}

double PerturbedMap::error_field(double x, double y, Vec2* grad) const {
    const double gx = x / lambda_x_;
    const double gy = y / lambda_y_;
    const int ix = static_cast<int>(std::floor(gx));
    const int iy = static_cast<int>(std::floor(gy));
    const double fx = gx - ix;
    const double fy = gy - iy;

    // Smoothstep gives a C1 field, so the injected error has a well-defined
    // gradient rather than the corners a linear blend would leave.
    const double ux = fx * fx * (3.0 - 2.0 * fx);
    const double uy = fy * fy * (3.0 - 2.0 * fy);
    const double dux = 6.0 * fx * (1.0 - fx);
    const double duy = 6.0 * fy * (1.0 - fy);

    const double a = lattice(ix,     iy,     seed_);
    const double b = lattice(ix + 1, iy,     seed_);
    const double c = lattice(ix,     iy + 1, seed_);
    const double d = lattice(ix + 1, iy + 1, seed_);

    const double top = a + (b - a) * ux;
    const double bot = c + (d - c) * ux;
    const double value = top + (bot - top) * uy;

    if (grad) {
        const double dv_dgx = ((b - a) * (1.0 - uy) + (d - c) * uy) * dux;
        const double dv_dgy = (bot - top) * duy;
        grad->x = scale_ * dv_dgx / lambda_x_;
        grad->y = scale_ * dv_dgy / lambda_y_;
    }
    return scale_ * value;
}

double PerturbedMap::elevation(double x, double y) const {
    return base_.elevation(x, y) + error_field(x, y, nullptr);
}

Vec2 PerturbedMap::gradient(double x, double y) const {
    Vec2 eg;
    error_field(x, y, &eg);
    const Vec2 bg = base_.gradient(x, y);
    return Vec2{bg.x + eg.x, bg.y + eg.y};
}

std::string PerturbedMap::describe() const {
    return "exact grid + injected error: " + std::to_string(static_cast<int>(amplitude_)) +
           " m RMS, lambda " + std::to_string(static_cast<int>(lambda_x_)) + " x " +
           std::to_string(static_cast<int>(lambda_y_)) + " m";
}
