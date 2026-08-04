#include "navsim.hpp"

#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <random>
#include <stdexcept>

namespace {
constexpr double kPi = 3.14159265358979323846;
constexpr double kDeg2Rad = kPi / 180.0;

double distance(double ax, double ay, double bx, double by) {
    const double dx = ax - bx;
    const double dy = ay - by;
    return std::sqrt(dx * dx + dy * dy);
}
}  // namespace

NavSim::NavSim(const Dem& truth_dem, const TerrainMap& map_dem,
               const ScenarioConfig& scenario, const PfConfig& pf)
    : truth_dem_(truth_dem), map_dem_(map_dem), scenario_(scenario), pf_config_(pf),
      filter_(pf, map_dem, scenario.seed ^ 0x9e3779b97f4a7c15ull) {
    altitude_ = truth_dem_.max_elevation() + scenario_.clearance;
}

RunSummary NavSim::run(std::ostream* log) {
    std::mt19937_64 rng(scenario_.seed);
    std::normal_distribution<double> unit(0.0, 1.0);

    const double heading = scenario_.heading_deg * kDeg2Rad;
    const double vx = scenario_.speed * std::cos(heading);
    const double vy = scenario_.speed * std::sin(heading);

    // The inertial platform carries a fixed, unknown velocity bias. This is what
    // makes dead reckoning walk away linearly with time, and it is exactly what
    // the bias-estimating filter modes are trying to recover.
    // Direction is uniform on the circle. This was previously a normal(0, 3 rad)
    // draw, which wraps to something close to uniform but reads as though the
    // bias had a preferred bearing. Changing it re-rolls every seeded result, so
    // absolute numbers shift; the distribution it samples does not.
    std::uniform_real_distribution<double> bearing(-kPi, kPi);
    const double bias_angle = bearing(rng);
    const Vec2 true_bias{scenario_.ins_bias * std::cos(bias_angle),
                         scenario_.ins_bias * std::sin(bias_angle)};

    double true_x = scenario_.start_x;
    double true_y = scenario_.start_y;

    // Dead reckoning and the filter start from the same wrong guess, so the
    // comparison between them is apples to apples.
    std::uniform_real_distribution<double> offset(-1.0, 1.0);
    double dr_x = true_x + offset(rng) * 400.0;
    double dr_y = true_y + offset(rng) * 400.0;

    filter_.initialize(dr_x, dr_y);

    history_.clear();
    const auto steps = static_cast<long>(scenario_.duration / scenario_.dt);
    history_.reserve(static_cast<std::size_t>(steps));

    const bool estimates_bias = pf_config_.mode != FilterMode::Position2D;

    if (log) {
        *log << std::fixed << std::setprecision(1);
        *log << "\n" << std::setw(8) << "t(s)" << std::setw(14) << "dead-reckon"
             << std::setw(14) << "terrain-aided" << std::setw(11) << "spread"
             << std::setw(10) << "N_eff" << std::setw(11) << "roughness";
        if (estimates_bias) *log << std::setw(12) << "bias err";
        *log << "\n" << std::setw(8) << "" << std::setw(14) << "error(m)"
             << std::setw(14) << "error(m)" << std::setw(11) << "(m)"
             << std::setw(10) << "" << std::setw(11) << "(m)";
        if (estimates_bias) *log << std::setw(12) << "(m/s)";
        *log << "\n";
    }

    RunSummary summary;
    summary.true_bias = true_bias;

    double sum_below = 0.0;
    long count_below = 0;
    long consecutive_above = 0;
    long consecutive_below = 0;
    double pending_fix_time = -1.0;
    double pending_loss_time = -1.0;
    double pending_loss_roughness = 0.0;
    double pending_loss_error = 0.0;
    double error_at_loss = 0.0;
    // A fix has to persist to count. One lucky step inside the threshold is not
    // localisation, and over flat ground the wandering estimate will clip below
    // it now and then purely by chance.
    constexpr long kStepsToDeclareFix = 10;
    constexpr long kStepsToDeclareLoss = 10;

    for (long step = 0; step < steps; ++step) {
        const double t = step * scenario_.dt;

        if (step > 0) {
            true_x += vx * scenario_.dt;
            true_y += vy * scenario_.dt;
        }
        if (!truth_dem_.in_bounds(true_x, true_y)) {
            if (log) *log << "\ntrack left the map at t = " << t << " s\n";
            break;
        }

        // --- inertial measurement -------------------------------------------
        const Vec2 measured_velocity{vx + true_bias.x + scenario_.ins_noise * unit(rng),
                                     vy + true_bias.y + scenario_.ins_noise * unit(rng)};

        if (step > 0) {
            dr_x += measured_velocity.x * scenario_.dt;
            dr_y += measured_velocity.y * scenario_.dt;
            filter_.predict(measured_velocity, scenario_.dt);
        }

        // --- terrain measurement ---------------------------------------------
        // A radar altimeter gives height above ground; a barometer gives height
        // above sea level. Their difference is the ground elevation underneath —
        // the single scalar per second that the whole filter runs on.
        const double ground_truth = truth_dem_.elevation(true_x, true_y);
        const double radar = (altitude_ - ground_truth) + scenario_.radar_sigma * unit(rng);
        const double baro = altitude_ + scenario_.baro_sigma * unit(rng);
        const double ground_measured = baro - radar;

        filter_.update(ground_measured);
        // Capture N_eff BEFORE resampling. resample_if_needed() ends by
        // recomputing the estimate from freshly uniform weights, so reading it
        // afterwards yields exactly N on every step that resampled and is
        // otherwise floored at the resample threshold — a starvation indicator
        // that cannot observe starvation.
        const double neff_before_resample = filter_.effective_sample_size();
        filter_.resample_if_needed();

        // --- bookkeeping ------------------------------------------------------
        StepRecord rec;
        rec.t = t;
        rec.true_x = true_x;
        rec.true_y = true_y;
        rec.dr_x = dr_x;
        rec.dr_y = dr_y;
        rec.pf_x = filter_.mean_x();
        rec.pf_y = filter_.mean_y();
        rec.dr_error = distance(dr_x, dr_y, true_x, true_y);
        rec.pf_error = distance(rec.pf_x, rec.pf_y, true_x, true_y);
        rec.spread = filter_.spread();
        rec.neff = neff_before_resample;
        rec.ground_truth = ground_truth;
        rec.ground_measured = ground_measured;
        rec.roughness = truth_dem_.roughness(true_x, true_y, 1500.0);
        rec.est_bias = filter_.mean_bias();
        rec.bias_error = norm(rec.est_bias - true_bias);
        rec.bias_spread = filter_.bias_spread();
        history_.push_back(rec);

        summary.max_dr_error = std::max(summary.max_dr_error, rec.dr_error);
        summary.min_neff_fraction = std::min(summary.min_neff_fraction,
                                             rec.neff / static_cast<double>(pf_config_.count));

        // Confidence comes from the posterior spread, not from the error, which
        // is only observable here because this is a simulation.
        if (rec.spread < summary.spread_threshold) {
            if (consecutive_below == 0) pending_fix_time = t;
            ++consecutive_below;
            if (consecutive_below >= kStepsToDeclareFix && !summary.ever_converged) {
                summary.ever_converged = true;
                summary.first_converge_time = pending_fix_time;
            }
            if (summary.ever_converged) {
                sum_below += rec.pf_error;
                ++count_below;
            }
            consecutive_above = 0;
            pending_loss_time = -1.0;
        } else {
            consecutive_below = 0;
            pending_fix_time = -1.0;

            if (summary.ever_converged) {
                if (consecutive_above == 0) {
                    pending_loss_time = t;
                    pending_loss_roughness = rec.roughness;
                    // Record the error at the moment the spread first exceeded
                    // the threshold, not ten steps later when loss is declared:
                    // coast_seconds is measured from this instant, so sampling
                    // the error later would divide a shorter numerator by a
                    // longer interval.
                    pending_loss_error = rec.pf_error;
                }
                ++consecutive_above;
                if (consecutive_above >= kStepsToDeclareLoss && !summary.lost_fix) {
                    summary.lost_fix = true;
                    summary.lost_fix_time = pending_loss_time;
                    summary.roughness_at_loss = pending_loss_roughness;
                    error_at_loss = pending_loss_error;
                }
            }
        }

        if (log && (step % 20 == 0 || step == steps - 1)) {
            *log << std::setw(8) << t
                 << std::setw(14) << rec.dr_error
                 << std::setw(14) << rec.pf_error
                 << std::setw(11) << rec.spread
                 << std::setw(10) << std::setprecision(0) << rec.neff << std::setprecision(1)
                 << std::setw(11) << rec.roughness;
            if (estimates_bias) *log << std::setw(12) << std::setprecision(3)
                                     << rec.bias_error << std::setprecision(1);
            *log << "\n";
        }
    }

    if (history_.empty()) throw std::runtime_error("no steps ran — check the start position");

    const StepRecord& last = history_.back();
    summary.final_pf_error = last.pf_error;
    summary.final_dr_error = last.dr_error;
    summary.final_est_bias = last.est_bias;
    summary.final_bias_error = last.bias_error;
    summary.mean_error_while_converged = count_below > 0 ? sum_below / count_below : 0.0;
    summary.fraction_converged =
        static_cast<double>(count_below) / static_cast<double>(history_.size());

    // How fast the solution degrades once the terrain stops helping. This is the
    // number bias calibration is supposed to improve: a filter that has solved
    // the bias should coast far better than one that has not.
    if (summary.lost_fix) {
        summary.coast_seconds = last.t - summary.lost_fix_time;
        if (summary.coast_seconds > 0.0) {
            summary.coast_drift_rate = (last.pf_error - error_at_loss) / summary.coast_seconds;
        }
    }
    return summary;
}

void write_history_csv(const std::vector<StepRecord>& history, const std::string& path) {
    std::ofstream out(path);
    if (!out) {
        std::cerr << "warning: cannot write " << path << "\n";
        return;
    }
    out << "t,true_x,true_y,dr_x,dr_y,pf_x,pf_y,dr_error,pf_error,spread,neff,"
           "ground_truth,ground_measured,roughness,est_bias_x,est_bias_y,bias_error,bias_spread\n";
    out << std::fixed << std::setprecision(4);
    for (const auto& r : history) {
        out << r.t << ',' << r.true_x << ',' << r.true_y << ',' << r.dr_x << ',' << r.dr_y
            << ',' << r.pf_x << ',' << r.pf_y << ',' << r.dr_error << ',' << r.pf_error
            << ',' << r.spread << ',' << r.neff << ',' << r.ground_truth << ','
            << r.ground_measured << ',' << r.roughness << ',' << r.est_bias.x << ','
            << r.est_bias.y << ',' << r.bias_error << ',' << r.bias_spread << "\n";
    }
}
