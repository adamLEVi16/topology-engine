#pragma once

#include <cstdint>
#include <iosfwd>
#include <string>
#include <vector>

#include "dem.hpp"
#include "particle_filter.hpp"

struct ScenarioConfig {
    double speed        = 120.0;   // m/s ground speed
    double heading_deg  = 20.0;    // 0 = due east, measured counter-clockwise
    double duration     = 260.0;   // s
    double dt           = 1.0;     // s between terrain fixes
    double clearance    = 700.0;   // m flown above the highest ground on the map

    double radar_sigma  = 3.0;     // m — radar altimeter noise
    double baro_sigma    = 9.0;    // m — barometric altitude noise
    double ins_bias     = 1.2;     // m/s — constant inertial velocity error
    double ins_noise    = 0.25;    // m/s — white inertial noise

    double start_x      = 2500.0;  // m, initial true position
    double start_y      = 2500.0;
    std::uint64_t seed  = 7u;
};

struct StepRecord {
    double t = 0.0;
    double true_x = 0.0, true_y = 0.0;
    double dr_x = 0.0,   dr_y = 0.0;    // dead reckoning, inertial only
    double pf_x = 0.0,   pf_y = 0.0;    // terrain-aided estimate
    double dr_error = 0.0;
    double pf_error = 0.0;
    double spread = 0.0;
    double neff = 0.0;
    double ground_truth = 0.0;          // true elevation beneath the vehicle
    double ground_measured = 0.0;       // what the sensors reported
    double roughness = 0.0;             // local terrain std-dev, the information source
};

struct RunSummary {
    double final_pf_error = 0.0;
    double final_dr_error = 0.0;
    double max_dr_error = 0.0;

    // A fix is declared from the posterior spread, never from the true error.
    // A real vehicle has no access to its own error — if it did, it would not
    // need the filter. Spread is the only confidence signal actually available
    // in flight, and over uninformative terrain it simply never collapses.
    double spread_threshold = 200.0;     // m

    bool   ever_converged = false;
    double first_converge_time = -1.0;   // s at which the error first drops below
    double mean_error_while_converged = 0.0;
    double fraction_converged = 0.0;     // share of the flight holding a fix

    // A fix can be won and then lost again — flying from informative terrain
    // onto a plain does exactly that — so losing it is tracked separately from
    // never having had one.
    bool   lost_fix = false;
    double lost_fix_time = -1.0;
    double roughness_at_loss = 0.0;
};

class NavSim {
public:
    NavSim(const Dem& dem, const ScenarioConfig& scenario, const PfConfig& pf);

    RunSummary run(std::ostream* log);

    const std::vector<StepRecord>& history() const { return history_; }
    const ParticleFilter& filter() const { return filter_; }
    double altitude() const { return altitude_; }

private:
    const Dem& dem_;
    ScenarioConfig scenario_;
    ParticleFilter filter_;
    std::vector<StepRecord> history_;
    double altitude_ = 0.0;
};

// Writes the per-step history as CSV for plotting.
void write_history_csv(const std::vector<StepRecord>& history, const std::string& path);
