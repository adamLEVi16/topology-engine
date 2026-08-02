#pragma once

#include <string>

// Everything is in Lennard-Jones reduced units:
//   length   sigma
//   energy   epsilon
//   mass     m
//   time     sigma * sqrt(m / epsilon)
//   temp     epsilon / k_B
// See README.md for the conversion table to argon in SI units.
struct Params {
    enum class Thermostat { None, Berendsen, Langevin };

    int    cells_per_side = 6;       // FCC conventional cells per side; N = 4 * n^3
    double density        = 0.8442;  // rho* — Rahman/Verlet liquid-argon state point
    double temperature    = 0.722;   // T*   — same state point
    double dt             = 0.004;   // reduced time units
    double cutoff         = 2.5;     // pair-potential cutoff in sigma

    long   equil_steps    = 2000;    // run under the thermostat
    long   prod_steps      = 5000;   // run in NVE and measure
    int    report_every   = 500;
    int    sample_every   = 20;      // RDF / averaging stride during production

    Thermostat thermostat = Thermostat::Berendsen;
    double tau            = 0.10;    // Berendsen coupling time
    double friction       = 1.0;     // Langevin friction gamma

    unsigned seed         = 20260802u;
    bool   disable_cells  = false;   // force the O(N^2) path, for validation
    int    rdf_bins       = 200;
    std::string rdf_path;            // optional: write g(r) here
    std::string traj_path;           // optional: write an XYZ trajectory here
};
