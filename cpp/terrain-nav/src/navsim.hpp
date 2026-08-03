#pragma once

#include <cstdint>
#include <iosfwd>
#include <string>
#include <vector>

#include "dem.hpp"
#include "linalg2.hpp"
#include "particle_filter.hpp"

struct ScenarioConfig {
    double speed        = 120.0;   // m/s ground speed
    double heading_deg  = 20.0;    // 0 = due east, measured counter-clockwise
    double duration     = 260.0;   // s
    double dt           = 1.0;     // s between terrain fixes
    double clearance    = 700.0;   // m flown above the highest ground on the map

    double radar_sigma  = 3.0;     // m — radar altimeter noise
    double baro_sigma   = 9.0;     // m — barometric altitude noise
    double ins_bias     = 1.2;     // m/s — magnitude of the constant inertial bias
    double ins_noise    = 0.25;    // m/s — white inertial noise

    double start_x      = 2500.0;
    double start_y      = 2500.0;
    std::uint64_t seed  = 7u;
};

struct StepRecord {
    double t = 0.0;
    double true_x = 0.0, true_y = 0.0;
    double dr_x = 0.0,   dr_y = 0.0;
    double pf_x = 0.0,   pf_y = 0.0;
    double dr_error = 0.0;
    double pf_error = 0.0;
    double spread = 0.0;
    double neff = 0.0;
    double ground_truth = 0.0;
    double ground_measured = 0.0;
    double roughness = 0.0;

    Vec2   est_bias;                 // filter's estimate of the inertial bias
    double bias_error = 0.0;         // m/s from the true bias
    double bias_spread = 0.0;        // filter's own uncertainty about the bias
};

struct RunSummary {
    double final_pf_error = 0.0;
    double final_dr_error = 0.0;
    double max_dr_error = 0.0;

    // A fix is declared from the posterior spread, never from the true error.
    // A real vehicle has no access to its own error — if it did, it would not
    // need the filter.
    double spread_threshold = 200.0;

    bool   ever_converged = false;
    double first_converge_time = -1.0;
    double mean_error_while_converged = 0.0;
    double fraction_converged = 0.0;

    bool   lost_fix = false;
    double lost_fix_time = -1.0;
    double roughness_at_loss = 0.0;

    // Lowest effective sample size seen — the particle-starvation indicator.
    double min_neff_fraction = 1.0;

    // Bias calibration, and what it buys once the terrain runs out.
    Vec2   true_bias;
    Vec2   final_est_bias;
    double final_bias_error = 0.0;      // m/s
    double coast_drift_rate = 0.0;      // m/s of position error growth after the fix is lost
    double coast_seconds = 0.0;
};

class NavSim {
public:
    // truth_dem is the ground the vehicle actually flies over; map_dem is the
    // stored map the filter navigates against. They are the same object unless
    // the map is deliberately degraded.
    NavSim(const Dem& truth_dem, const Dem& map_dem,
           const ScenarioConfig& scenario, const PfConfig& pf);

    RunSummary run(std::ostream* log);

    const std::vector<StepRecord>& history() const { return history_; }
    const ParticleFilter& filter() const { return filter_; }
    double altitude() const { return altitude_; }

private:
    const Dem& truth_dem_;
    const Dem& map_dem_;
    ScenarioConfig scenario_;
    PfConfig pf_config_;
    ParticleFilter filter_;
    std::vector<StepRecord> history_;
    double altitude_ = 0.0;
};

void write_history_csv(const std::vector<StepRecord>& history, const std::string& path);
