#pragma once

#include <cstdint>
#include <random>
#include <vector>

#include "terrain_map.hpp"
#include "linalg2.hpp"

struct Particle {
    double x = 0.0;
    double y = 0.0;

    // Inertial velocity bias, in m/s.
    //   Bootstrap4D      — a sampled point in bias space, one hypothesis per particle
    //   RaoBlackwellized — the mean of this particle's Gaussian over bias
    //   Position2D       — unused
    Vec2 bias;
    Mat2 bias_cov;          // RaoBlackwellized only

    double log_weight = 0.0;
};

enum class FilterMode {
    Position2D,        // (x, y) only; inertial bias absorbed into process noise
    Bootstrap4D,       // (x, y, bx, by) all sampled — the brute-force baseline
    RaoBlackwellized,  // particles in (x, y); an exact 2x2 Kalman filter per particle for bias
};

struct PfConfig {
    FilterMode mode          = FilterMode::Position2D;
    int    count             = 5000;
    double init_radius       = 1500.0;  // m — half-width of the initial position box
    double process_noise     = 12.0;    // m per update
    double meas_sigma        = 10.0;    // m — assumed elevation measurement noise
    double roughening        = 4.0;     // m — position jitter after resampling
    double resample_fraction = 0.5;

    // Bias-estimating modes only.
    double bias_prior        = 3.0;     // m/s — initial bias uncertainty (1 sigma)
    double bias_walk         = 0.004;   // m/s per step — how fast the bias may wander
    double bias_roughening   = 0.02;    // m/s — bias jitter after resampling (4D only)

    // --- map error model -----------------------------------------------------
    // The DEM is not truth. It has a vertical accuracy, and — far more
    // dangerously on steep ground — a horizontal registration error. A lateral
    // map offset of d metres on a slope of gradient g looks like a vertical
    // error of |g|·d, which on a 45-degree face equals d exactly. Ignore that
    // and the filter kills its own correct particles on every ridge.
    bool   inflate_on_gradient = false;  // scale measurement variance by local slope
    double map_vertical_sigma  = 3.0;    // m — DEM vertical accuracy
    double map_horizontal_sigma = 12.0;  // m — DEM horizontal registration accuracy

    // Deliberate misregistration of the stored map, for testing. The filter
    // queries the DEM at (x + shift), while truth is sampled unshifted.
    double map_shift_x = 0.0;
    double map_shift_y = 0.0;
};

// Particle filter over horizontal position, optionally co-estimating the
// inertial velocity bias. See the README for why the measurement equation
// z = DEM(x, y) rules out a Kalman filter on the position states.
class ParticleFilter {
public:
    ParticleFilter(const PfConfig& config, const TerrainMap& dem, std::uint64_t seed);

    void initialize(double x0, double y0);

    // Propagate one step given the inertially reported velocity. Bias-aware
    // modes subtract their own bias estimate from it; Position2D does not.
    void predict(const Vec2& measured_velocity, double dt);

    void update(double measured_ground_elevation);
    void resample_if_needed();

    double mean_x() const { return mean_x_; }
    double mean_y() const { return mean_y_; }
    Vec2   mean_bias() const { return mean_bias_; }
    double bias_spread() const;             // RMS bias uncertainty, m/s
    double spread() const;                  // RMS horizontal distance from the mean
    double effective_sample_size() const { return neff_; }
    bool   resampled_last_update() const { return resampled_; }
    // Weighted mean of the per-particle measurement sigma actually used on the
    // last update — flat where the ground is flat, inflated on slopes.
    double mean_effective_sigma() const { return mean_eff_sigma_; }
    // Non-zero means the map returned NaN or infinity — the map is corrupt, and
    // any result from this run should be discarded rather than interpreted.
    long nonfinite_queries() const { return nonfinite_queries_; }

    const std::vector<Particle>& particles() const { return particles_; }
    const std::vector<double>& weights() const { return lin_weights_; }

private:
    void refresh_estimate();
    void normalize_weights();
    Vec2 sample_gaussian(const Mat2& covariance);

    PfConfig config_;
    const TerrainMap& dem_;
    std::vector<Particle> particles_;
    std::vector<Particle> scratch_;
    std::vector<double> lin_weights_;
    std::mt19937_64 rng_;

    double mean_x_ = 0.0;
    double mean_y_ = 0.0;
    Vec2   mean_bias_;
    double neff_ = 0.0;
    double mean_eff_sigma_ = 0.0;
    long   nonfinite_queries_ = 0;
    bool   resampled_ = false;
};
