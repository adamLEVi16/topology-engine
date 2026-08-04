#include "particle_filter.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

ParticleFilter::ParticleFilter(const PfConfig& config, const TerrainMap& dem, std::uint64_t seed)
    : config_(config), dem_(dem), seed_(seed), rng_(seed) {
    if (config_.count < 2) throw std::invalid_argument("particle count must be >= 2");
    if (config_.meas_sigma <= 0.0) throw std::invalid_argument("meas_sigma must be > 0");
    if (config_.process_noise <= 0.0) throw std::invalid_argument("process_noise must be > 0");
    particles_.resize(static_cast<std::size_t>(config_.count));
    scratch_.resize(particles_.size());
    lin_weights_.assign(particles_.size(), 1.0 / config_.count);
}

Vec2 ParticleFilter::sample_gaussian(const Mat2& covariance) {
    std::normal_distribution<double> unit(0.0, 1.0);
    const Mat2 l = cholesky(covariance);
    const double n0 = unit(rng_);
    const double n1 = unit(rng_);
    return Vec2{l.m00 * n0, l.m10 * n0 + l.m11 * n1};
}

void ParticleFilter::initialize(double x0, double y0) {
    // Full reset, not just the particles. Re-seeding the generator and clearing
    // the diagnostics is what makes a second initialize() on the same object
    // reproduce the first exactly; without it the RNG stream would carry over
    // and repeated runs would silently diverge.
    rng_.seed(seed_);
    nonfinite_queries_ = 0;
    mean_eff_sigma_ = 0.0;
    neff_ = 0.0;
    resampled_ = false;

    // A uniform box for position: before the first terrain fix we genuinely have
    // no idea where in the uncertainty region we are, and a Gaussian prior would
    // understate the tails the filter has to search.
    std::uniform_real_distribution<double> ux(x0 - config_.init_radius, x0 + config_.init_radius);
    std::uniform_real_distribution<double> uy(y0 - config_.init_radius, y0 + config_.init_radius);
    // The bias prior is Gaussian, and deliberately identical for both bias-aware
    // modes so the comparison between them is not confounded by the prior.
    std::normal_distribution<double> bias_prior(0.0, config_.bias_prior);

    for (auto& p : particles_) {
        p.x = ux(rng_);
        p.y = uy(rng_);
        p.log_weight = 0.0;

        switch (config_.mode) {
            case FilterMode::Position2D:
                p.bias = Vec2{};
                break;
            case FilterMode::Bootstrap4D:
                p.bias = Vec2{bias_prior(rng_), bias_prior(rng_)};
                break;
            case FilterMode::RaoBlackwellized:
                p.bias = Vec2{};
                p.bias_cov = Mat2::identity(config_.bias_prior * config_.bias_prior);
                break;
        }
    }
    std::fill(lin_weights_.begin(), lin_weights_.end(), 1.0 / config_.count);
    refresh_estimate();
}

void ParticleFilter::predict(const Vec2& measured_velocity, double dt) {
    const double q = config_.process_noise * config_.process_noise;
    const Mat2 process_cov = Mat2::identity(q);
    std::normal_distribution<double> pos_jitter(0.0, config_.process_noise);
    std::normal_distribution<double> bias_jitter(0.0, config_.bias_walk);

    for (auto& p : particles_) {
        switch (config_.mode) {
            case FilterMode::Position2D: {
                p.x += measured_velocity.x * dt + pos_jitter(rng_);
                p.y += measured_velocity.y * dt + pos_jitter(rng_);
                break;
            }

            case FilterMode::Bootstrap4D: {
                // Each particle is one joint hypothesis about position and bias.
                // The bias is never measured directly; wrong-bias particles simply
                // walk off terrain-consistent ground and die at resampling.
                const Vec2 v = measured_velocity - p.bias;
                p.x += v.x * dt + pos_jitter(rng_);
                p.y += v.y * dt + pos_jitter(rng_);
                p.bias.x += bias_jitter(rng_);
                p.bias.y += bias_jitter(rng_);
                break;
            }

            case FilterMode::RaoBlackwellized: {
                // Marginalised prediction. The step is drawn from the covariance
                // that accounts for both process noise and this particle's own
                // bias uncertainty, so a particle unsure of its bias takes a
                // correspondingly wider step.
                const Vec2 nominal = (measured_velocity - p.bias) * dt;
                const Mat2 s = p.bias_cov * (dt * dt) + process_cov;
                const Vec2 step = nominal + sample_gaussian(s);

                p.x += step.x;
                p.y += step.y;

                // The realised step is now a linear measurement of the bias:
                //   step = (v_meas - b)*dt + w,   so   H = -dt * I
                // This is the whole trick — the terrain never sees the bias, but
                // the displacement does.
                const Vec2 innovation = step - nominal;
                const Mat2 s_inv = inverse(s);
                const Mat2 gain = p.bias_cov * s_inv * (-dt);

                p.bias += gain * innovation;
                p.bias_cov = (Mat2::identity() - gain * Mat2::identity(-dt)) * p.bias_cov;

                // Bias random walk, keeping the filter able to track slow changes.
                p.bias_cov = p.bias_cov + Mat2::identity(config_.bias_walk * config_.bias_walk);
                break;
            }
        }
    }
}

void ParticleFilter::update(double measured_ground_elevation) {
    const double sensor_var = config_.meas_sigma * config_.meas_sigma;
    const double map_v_var = config_.map_vertical_sigma * config_.map_vertical_sigma;
    const double map_h_var = config_.map_horizontal_sigma * config_.map_horizontal_sigma;

    double sigma_accum = 0.0;
    double sigma_weight = 0.0;

    for (std::size_t k = 0; k < particles_.size(); ++k) {
        Particle& p = particles_[k];
        const double qx = p.x + config_.map_shift_x;
        const double qy = p.y + config_.map_shift_y;

        if (!dem_.in_bounds(qx, qy)) {
            // Off the map: not impossible, just unsupported. A large finite
            // penalty rather than -inf keeps the filter recoverable if every
            // particle drifts outside at once.
            p.log_weight += -50.0;
            continue;
        }

        double variance = sensor_var;
        if (config_.inflate_on_gradient) {
            // First-order propagation of horizontal map error into vertical:
            //   var_eff = var_sensor + var_map_v + g^T * Sigma_xy * g
            // with Sigma_xy isotropic. On flat ground this reduces to the
            // sensor noise; on a 45-degree slope (|g| = 1) it adds the full
            // horizontal registration variance.
            const Vec2 g = dem_.gradient(qx, qy);
            variance += map_v_var + (g.x * g.x + g.y * g.y) * map_h_var;
        }

        const double map_elevation = dem_.elevation(qx, qy);
        if (!std::isfinite(map_elevation) || !std::isfinite(variance)) {
            // A corrupt map (bad weights, truncated file) would otherwise put a
            // NaN into log_weight. std::max propagates the other operand past a
            // NaN, so max_lw stays -inf, every exp() returns NaN, and the
            // normalisation guard silently resets to a uniform cloud — a wrecked
            // filter that still reports plausible numbers. Count it instead.
            ++nonfinite_queries_;
            p.log_weight += -50.0;
            continue;
        }
        const double innovation = measured_ground_elevation - map_elevation;

        // The -0.5*log(variance) term is NOT optional once the variance varies
        // per particle. With a constant sigma it is a shared constant that
        // cancels in normalisation; here, dropping it would hand every particle
        // sitting on a cliff a free weight bonus, because exp(-d^2/2s^2) tends
        // to 1 as s grows. The filter would then drift onto steep ground.
        p.log_weight += -0.5 * innovation * innovation / variance
                        - 0.5 * std::log(variance);

        sigma_accum += lin_weights_[k] * std::sqrt(variance);
        sigma_weight += lin_weights_[k];
    }

    mean_eff_sigma_ = (sigma_weight > 0.0) ? sigma_accum / sigma_weight : config_.meas_sigma;

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
    double mx = 0.0, my = 0.0, bx = 0.0, by = 0.0, sum_sq = 0.0;
    for (std::size_t k = 0; k < particles_.size(); ++k) {
        const double w = lin_weights_[k];
        mx += w * particles_[k].x;
        my += w * particles_[k].y;
        bx += w * particles_[k].bias.x;
        by += w * particles_[k].bias.y;
        sum_sq += w * w;
    }
    mean_x_ = mx;
    mean_y_ = my;
    mean_bias_ = Vec2{bx, by};
    neff_ = (sum_sq > 0.0) ? 1.0 / sum_sq : 0.0;
}

double ParticleFilter::spread() const {
    double var = 0.0;
    for (std::size_t k = 0; k < particles_.size(); ++k) {
        const double dx = particles_[k].x - mean_x_;
        const double dy = particles_[k].y - mean_y_;
        var += lin_weights_[k] * (dx * dx + dy * dy);
    }
    return std::sqrt(std::max(0.0, var));
}

double ParticleFilter::bias_spread() const {
    // Total marginal variance of the mixture: the spread between particle means
    // plus, for the Rao-Blackwellised filter, each particle's own covariance.
    // Ignoring the second term would badly understate the uncertainty, because
    // most of it lives inside the per-particle Kalman filters.
    double var = 0.0;
    for (std::size_t k = 0; k < particles_.size(); ++k) {
        const Vec2 d = particles_[k].bias - mean_bias_;
        double term = d.x * d.x + d.y * d.y;
        if (config_.mode == FilterMode::RaoBlackwellized) {
            term += particles_[k].bias_cov.m00 + particles_[k].bias_cov.m11;
        }
        var += lin_weights_[k] * term;
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
    std::normal_distribution<double> bias_jitter(0.0, config_.bias_roughening);
    for (auto& p : particles_) {
        p.x += jitter(rng_);
        p.y += jitter(rng_);
        // Only the bootstrap filter needs bias roughening: its bias lives in the
        // sampled points, which deplete. The Rao-Blackwellised filter keeps its
        // bias uncertainty in each particle's covariance, and jittering the
        // means there would inject noise the Kalman recursion already accounts for.
        if (config_.mode == FilterMode::Bootstrap4D) {
            p.bias.x += bias_jitter(rng_);
            p.bias.y += bias_jitter(rng_);
        }
    }

    std::fill(lin_weights_.begin(), lin_weights_.end(), 1.0 / n);
    resampled_ = true;
    refresh_estimate();
}
