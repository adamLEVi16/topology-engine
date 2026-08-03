#pragma once

#include <cstdint>
#include <random>
#include <vector>

#include "dem.hpp"

struct Particle {
    double x = 0.0;
    double y = 0.0;
    double log_weight = 0.0;
};

struct PfConfig {
    int    count             = 5000;
    double init_radius       = 1500.0;  // m — half-width of the initial uncertainty box
    double process_noise     = 12.0;    // m per update — models unmodelled INS error
    double meas_sigma        = 10.0;    // m — combined radar + baro elevation noise
    double roughening        = 4.0;     // m — jitter after resampling, fights depletion
    double resample_fraction = 0.5;     // resample when N_eff drops below this * count
};

// Bootstrap particle filter over 2-D horizontal position.
//
// The state is just (x, y). Inertial velocity error is folded into the process
// noise rather than estimated explicitly; see the README for the four-state
// version that estimates the INS bias directly.
class ParticleFilter {
public:
    ParticleFilter(const PfConfig& config, const Dem& dem, std::uint64_t seed);

    // Scatter particles uniformly in a box around the initial position guess.
    void initialize(double x0, double y0);

    // Propagate with the inertially-reported displacement, plus process noise.
    void predict(double dx, double dy);

    // Reweight against a measured ground elevation beneath the vehicle.
    void update(double measured_ground_elevation);

    void resample_if_needed();

    double mean_x() const { return mean_x_; }
    double mean_y() const { return mean_y_; }
    double spread() const;                  // RMS horizontal distance from the mean
    double effective_sample_size() const;
    bool   resampled_last_update() const { return resampled_; }

    const std::vector<Particle>& particles() const { return particles_; }

    // Normalised linear weights, parallel to particles().
    const std::vector<double>& weights() const { return lin_weights_; }

private:
    void refresh_estimate();
    void normalize_weights();

    PfConfig config_;
    const Dem& dem_;
    std::vector<Particle> particles_;
    std::vector<Particle> scratch_;
    std::vector<double> lin_weights_;
    std::mt19937_64 rng_;

    double mean_x_ = 0.0;
    double mean_y_ = 0.0;
    double neff_ = 0.0;
    bool   resampled_ = false;
};
