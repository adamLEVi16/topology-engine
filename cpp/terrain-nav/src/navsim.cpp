#include "navsim.hpp"

#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <random>
#include <stdexcept>

namespace {
constexpr double kDeg2Rad = 3.14159265358979323846 / 180.0;

double distance(double ax, double ay, double bx, double by) {
    const double dx = ax - bx;
    const double dy = ay - by;
    return std::sqrt(dx * dx + dy * dy);
}
}  // namespace

NavSim::NavSim(const Dem& dem, const ScenarioConfig& scenario, const PfConfig& pf)
    : dem_(dem), scenario_(scenario), filter_(pf, dem, scenario.seed ^ 0x9e3779b97f4a7c15ull) {
    altitude_ = dem_.max_elevation() + scenario_.clearance;
}

RunSummary NavSim::run(std::ostream* log) {
    std::mt19937_64 rng(scenario_.seed);
    std::normal_distribution<double> unit(0.0, 1.0);

    const double heading = scenario_.heading_deg * kDeg2Rad;
    const double vx = scenario_.speed * std::cos(heading);
    const double vy = scenario_.speed * std::sin(heading);

    // The inertial platform has a fixed, unknown velocity bias. This is what
    // makes dead reckoning walk away linearly with time, and it is exactly the
    // error terrain matching exists to bound.
    const double bias_angle = unit(rng) * 3.0;
    const double bias_x = scenario_.ins_bias * std::cos(bias_angle);
    const double bias_y = scenario_.ins_bias * std::sin(bias_angle);

    double true_x = scenario_.start_x;
    double true_y = scenario_.start_y;

    // Both the dead-reckoned and terrain-aided solutions start from the same
    // wrong guess, so the comparison is apples to apples.
    std::uniform_real_distribution<double> offset(-1.0, 1.0);
    const double init_err_x = offset(rng) * 400.0;
    const double init_err_y = offset(rng) * 400.0;
    double dr_x = true_x + init_err_x;
    double dr_y = true_y + init_err_y;

    filter_.initialize(dr_x, dr_y);

    history_.clear();
    const auto steps = static_cast<long>(scenario_.duration / scenario_.dt);
    history_.reserve(static_cast<std::size_t>(steps));

    if (log) {
        *log << std::fixed << std::setprecision(1);
        *log << "\n" << std::setw(8) << "t(s)" << std::setw(14) << "dead-reckon"
             << std::setw(14) << "terrain-aided" << std::setw(12) << "spread"
             << std::setw(10) << "N_eff" << std::setw(12) << "roughness" << "\n";
        *log << std::setw(8) << "" << std::setw(14) << "error(m)"
             << std::setw(14) << "error(m)" << std::setw(12) << "(m)"
             << std::setw(10) << "" << std::setw(12) << "(m)" << "\n";
    }

    RunSummary summary;
    double sum_below = 0.0;
    long count_below = 0;
    long consecutive_above = 0;
    long consecutive_below = 0;
    double pending_fix_time = -1.0;
    double pending_loss_time = -1.0;
    double pending_loss_roughness = 0.0;
    // A fix has to persist to count. One lucky step inside the threshold is not
    // localisation, and over flat ground the wandering estimate will clip below
    // it now and then purely by chance.
    constexpr long kStepsToDeclareFix = 10;
    constexpr long kStepsToDeclareLoss = 10;

    for (long step = 0; step < steps; ++step) {
        const double t = step * scenario_.dt;

        // --- truth advances -------------------------------------------------
        if (step > 0) {
            true_x += vx * scenario_.dt;
            true_y += vy * scenario_.dt;
        }
        if (!dem_.in_bounds(true_x, true_y)) {
            if (log) *log << "\ntrack left the map at t = " << t << " s\n";
            break;
        }

        // --- inertial measurement -------------------------------------------
        const double meas_vx = vx + bias_x + scenario_.ins_noise * unit(rng);
        const double meas_vy = vy + bias_y + scenario_.ins_noise * unit(rng);
        const double dx = meas_vx * scenario_.dt;
        const double dy = meas_vy * scenario_.dt;

        if (step > 0) {
            dr_x += dx;
            dr_y += dy;
            filter_.predict(dx, dy);
        }

        // --- terrain measurement --------------------------------------------
        // A radar altimeter gives height above ground; a barometer gives height
        // above sea level. Their difference is the ground elevation underneath —
        // the single scalar per second that the whole filter runs on.
        const double ground_truth = dem_.elevation(true_x, true_y);
        const double radar = (altitude_ - ground_truth) + scenario_.radar_sigma * unit(rng);
        const double baro = altitude_ + scenario_.baro_sigma * unit(rng);
        const double ground_measured = baro - radar;

        filter_.update(ground_measured);
        filter_.resample_if_needed();

        // --- bookkeeping -----------------------------------------------------
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
        rec.neff = filter_.effective_sample_size();
        rec.ground_truth = ground_truth;
        rec.ground_measured = ground_measured;
        rec.roughness = dem_.roughness(true_x, true_y, 1500.0);
        history_.push_back(rec);

        summary.max_dr_error = std::max(summary.max_dr_error, rec.dr_error);

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

            // Symmetrically, require a sustained excursion before calling the
            // fix lost, so one bad measurement doesn't read as a failure.
            if (summary.ever_converged) {
                if (consecutive_above == 0) {
                    pending_loss_time = t;
                    pending_loss_roughness = rec.roughness;
                }
                ++consecutive_above;
                if (consecutive_above >= kStepsToDeclareLoss && !summary.lost_fix) {
                    summary.lost_fix = true;
                    summary.lost_fix_time = pending_loss_time;
                    summary.roughness_at_loss = pending_loss_roughness;
                }
            }
        }

        if (log && (step % 20 == 0 || step == steps - 1)) {
            *log << std::setw(8) << t
                 << std::setw(14) << rec.dr_error
                 << std::setw(14) << rec.pf_error
                 << std::setw(12) << rec.spread
                 << std::setw(10) << std::setprecision(0) << rec.neff << std::setprecision(1)
                 << std::setw(12) << rec.roughness << "\n";
        }
    }

    if (history_.empty()) throw std::runtime_error("no steps ran — check the start position");

    summary.final_pf_error = history_.back().pf_error;
    summary.final_dr_error = history_.back().dr_error;
    summary.mean_error_while_converged = count_below > 0 ? sum_below / count_below : 0.0;
    summary.fraction_converged =
        static_cast<double>(count_below) / static_cast<double>(history_.size());
    return summary;
}

void write_history_csv(const std::vector<StepRecord>& history, const std::string& path) {
    std::ofstream out(path);
    if (!out) {
        std::cerr << "warning: cannot write " << path << "\n";
        return;
    }
    out << "t,true_x,true_y,dr_x,dr_y,pf_x,pf_y,dr_error,pf_error,spread,neff,"
           "ground_truth,ground_measured,roughness\n";
    out << std::fixed << std::setprecision(3);
    for (const auto& r : history) {
        out << r.t << ',' << r.true_x << ',' << r.true_y << ',' << r.dr_x << ',' << r.dr_y
            << ',' << r.pf_x << ',' << r.pf_y << ',' << r.dr_error << ',' << r.pf_error
            << ',' << r.spread << ',' << r.neff << ',' << r.ground_truth << ','
            << r.ground_measured << ',' << r.roughness << "\n";
    }
}
