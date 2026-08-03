#include "particle_filter.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

ParticleFilter::ParticleFilter(const PfConfig& config, const Dem& dem, std::uint64_t seed)
    : config_(config), dem_(dem), rng_(seed) {
    if (config_.count < 2) throw std::invalid_argument("particle count must be >= 2");
    if (config_.meas_sigma <= 0.0) throw std::invalid_argument("meas_sigma must be > 0");
    particles_.resize(static_cast<std::size_t>(config_.count));
    scratch_.resize(particles_.size());
    lin_weights_.assign(particles_.size(), 1.0 / config_.count);
}

void ParticleFilter::initialize(double x0, double y0) {
    // A uniform box, not a Gaussian: before the first terrain fix we genuinely
    // have no idea where in the uncertainty region we are, and a Gaussian prior
    // would understate the tails the filter has to search.
    std::uniform_real_distribution<double> ux(x0 - config_.init_radius, x0 + config_.init_radius);
    std::uniform_real_distribution<double> uy(y0 - config_.init_radius, y0 + config_.init_radius);

    for (auto& p : particles_) {
        p.x = ux(rng_);
        p.y = uy(rng_);
        p.log_weight = 0.0;
    }
    std::fill(lin_weights_.begin(), lin_weights_.end(), 1.0 / config_.count);
    refresh_estimate();
}

void ParticleFilter::predict(double dx, double dy) {
    std::normal_distribution<double> jitter(0.0, config_.process_noise);
    for (auto& p : particles_) {
        p.x += dx + jitter(rng_);
        p.y += dy + jitter(rng_);
    }
}

void ParticleFilter::update(double measured_ground_elevation) {
    const double inv_two_sigma2 = 1.0 / (2.0 * config_.meas_sigma * config_.meas_sigma);

    for (auto& p : particles_) {
        if (!dem_.in_bounds(p.x, p.y)) {
            // Off the map: not impossible, just unsupported. A large finite
            // penalty rather than -inf keeps the filter recoverable if every
            // particle drifts outside at once.
            p.log_weight += -50.0;
            continue;
        }
        const double innovation = measured_ground_elevation - dem_.elevation(p.x, p.y);
        p.log_weight += -innovation * innovation * inv_two_sigma2;
    }

    normalize_weights();
    refresh_estimate();
}

void ParticleFilter::normalize_weights() {
    // Log-sum-exp. Terrain likelihoods span enormous dynamic range — a particle
    // 200 m off in elevation with sigma = 10 m scores exp(-200), which underflows
    // to exactly zero in linear space and silently kills the filter.
    double max_lw = -std::numeric_limits<double>::infinity();
    for (const auto& p : particles_) max_lw = std::max(max_lw, p.log_weight);

    double sum = 0.0;
    for (std::size_t k = 0; k < particles_.size(); ++k) {
        lin_weights_[k] = std::exp(particles_[k].log_weight - max_lw);
        sum += lin_weights_[k];
    }

    if (!(sum > 0.0) || !std::isfinite(sum)) {
        // Total collapse. Fall back to a uniform cloud so the run continues
        // and the diagnostics show what happened.
        std::fill(lin_weights_.begin(), lin_weights_.end(), 1.0 / particles_.size());
        for (auto& p : particles_) p.log_weight = 0.0;
        return;
    }

    const double inv_sum = 1.0 / sum;
    for (std::size_t k = 0; k < particles_.size(); ++k) {
        lin_weights_[k] *= inv_sum;
        particles_[k].log_weight = std::log(lin_weights_[k]);
    }
}

void ParticleFilter::refresh_estimate() {
    double mx = 0.0;
    double my = 0.0;
    double sum_sq = 0.0;
    for (std::size_t k = 0; k < particles_.size(); ++k) {
        mx += lin_weights_[k] * particles_[k].x;
        my += lin_weights_[k] * particles_[k].y;
        sum_sq += lin_weights_[k] * lin_weights_[k];
    }
    mean_x_ = mx;
    mean_y_ = my;
    neff_ = (sum_sq > 0.0) ? 1.0 / sum_sq : 0.0;
}

double ParticleFilter::effective_sample_size() const { return neff_; }

double ParticleFilter::spread() const {
    double var = 0.0;
    for (std::size_t k = 0; k < particles_.size(); ++k) {
        const double dx = particles_[k].x - mean_x_;
        const double dy = particles_[k].y - mean_y_;
        var += lin_weights_[k] * (dx * dx + dy * dy);
    }
    return std::sqrt(std::max(0.0, var));
}

void ParticleFilter::resample_if_needed() {
    resampled_ = false;
    if (neff_ >= config_.resample_fraction * particles_.size()) return;

    // Systematic resampling: one uniform draw, then evenly spaced strata.
    // Lower variance than multinomial and O(N) instead of O(N log N).
    const std::size_t n = particles_.size();
    const double step = 1.0 / n;
    std::uniform_real_distribution<double> u0(0.0, step);
    double target = u0(rng_);

    double cumulative = lin_weights_[0];
    std::size_t src = 0;
    for (std::size_t m = 0; m < n; ++m) {
        while (target > cumulative && src + 1 < n) {
            ++src;
            cumulative += lin_weights_[src];
        }
        scratch_[m] = particles_[src];
        scratch_[m].log_weight = 0.0;
        target += step;
    }
    particles_.swap(scratch_);

    // Roughening. Resampling duplicates survivors, so without a little added
    // jitter the cloud collapses onto a handful of distinct points and can
    // never recover from an early mistake.
    std::normal_distribution<double> jitter(0.0, config_.roughening);
    for (auto& p : particles_) {
        p.x += jitter(rng_);
        p.y += jitter(rng_);
    }

    std::fill(lin_weights_.begin(), lin_weights_.end(), 1.0 / n);
    resampled_ = true;
    refresh_estimate();
}
