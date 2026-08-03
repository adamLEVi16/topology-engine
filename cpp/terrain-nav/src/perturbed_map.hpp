#pragma once

#include <string>

#include "dem.hpp"
#include "terrain_map.hpp"

// A perfect map plus a synthetic error field with independently controlled
// amplitude, spatial scale, and anisotropy.
//
// Comparing two different representations confounds a dozen properties at once.
// This wraps the exact truth grid instead, so the only difference from perfect
// knowledge is the error deliberately injected — one variable at a time.
class PerturbedMap : public TerrainMap {
public:
    // amplitude   RMS vertical error in metres
    // wavelength  spatial scale of the error in metres
    // aspect      wavelength multiplier along x; > 1 stretches error features
    //             along x, < 1 along y. With a due-east flight, > 1 is
    //             along-track and < 1 is cross-track.
    PerturbedMap(const Dem& base, double amplitude, double wavelength,
                 double aspect, unsigned seed);

    double elevation(double x, double y) const override;
    Vec2 gradient(double x, double y) const override;
    bool in_bounds(double x, double y) const override { return base_.in_bounds(x, y); }
    double extent_x() const override { return base_.extent_x(); }
    double extent_y() const override { return base_.extent_y(); }
    std::size_t memory_bytes() const override { return base_.memory_bytes(); }
    std::string describe() const override;

private:
    // Band-limited smooth noise, plus its exact derivative when grad is non-null.
    double error_field(double x, double y, Vec2* grad) const;
    void calibrate_amplitude(double target_rms);

    const Dem& base_;
    double amplitude_ = 0.0;
    double lambda_x_ = 1.0;
    double lambda_y_ = 1.0;
    double scale_ = 0.0;
    unsigned seed_ = 0;
};
