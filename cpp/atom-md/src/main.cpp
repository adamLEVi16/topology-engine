#include <cstdlib>
#include <cstring>
#include <exception>
#include <iostream>
#include <string>

#include "params.hpp"
#include "simulation.hpp"

namespace {

void print_usage(const char* argv0) {
    std::cout <<
        "Lennard-Jones molecular dynamics in reduced units.\n\n"
        "usage: " << argv0 << " [options]\n\n"
        "  --cells N          FCC cells per side; N_atoms = 4*N^3   (default 6 -> 864)\n"
        "  --density X        reduced density rho*                  (default 0.8442)\n"
        "  --temperature X    reduced temperature T*                (default 0.722)\n"
        "  --dt X             timestep in reduced time units        (default 0.004)\n"
        "  --cutoff X         pair cutoff in sigma                  (default 2.5)\n"
        "  --equil N          equilibration steps                   (default 2000)\n"
        "  --steps N          production steps                      (default 5000)\n"
        "  --thermostat S     none | berendsen | langevin           (default berendsen)\n"
        "  --tau X            Berendsen coupling time               (default 0.1)\n"
        "  --friction X       Langevin friction gamma               (default 1.0)\n"
        "  --seed N           RNG seed                              (default 20260802)\n"
        "  --report N         log every N steps                     (default 500)\n"
        "  --sample N         sample observables every N steps      (default 20)\n"
        "  --no-cells         force the O(N^2) pair loop (validation)\n"
        "  --rdf PATH         write the radial distribution function\n"
        "  --traj PATH        write an XYZ trajectory\n"
        "  --help             show this message\n\n"
        "Note: 'berendsen' thermostats the equilibration only; production then\n"
        "runs in NVE so energy conservation can be checked. 'langevin' keeps the\n"
        "thermostat on throughout and samples the canonical ensemble.\n";
}

// Fetches the value following a flag, or exits with a clear message.
const char* require_value(int argc, char** argv, int& i) {
    if (i + 1 >= argc) {
        std::cerr << "error: " << argv[i] << " needs a value\n";
        std::exit(2);
    }
    return argv[++i];
}

}  // namespace

int main(int argc, char** argv) {
    Params params;

    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--help" || arg == "-h") {
            print_usage(argv[0]);
            return 0;
        } else if (arg == "--cells") {
            params.cells_per_side = std::atoi(require_value(argc, argv, i));
        } else if (arg == "--density") {
            params.density = std::atof(require_value(argc, argv, i));
        } else if (arg == "--temperature") {
            params.temperature = std::atof(require_value(argc, argv, i));
        } else if (arg == "--dt") {
            params.dt = std::atof(require_value(argc, argv, i));
        } else if (arg == "--cutoff") {
            params.cutoff = std::atof(require_value(argc, argv, i));
        } else if (arg == "--equil") {
            params.equil_steps = std::atol(require_value(argc, argv, i));
        } else if (arg == "--steps") {
            params.prod_steps = std::atol(require_value(argc, argv, i));
        } else if (arg == "--tau") {
            params.tau = std::atof(require_value(argc, argv, i));
        } else if (arg == "--friction") {
            params.friction = std::atof(require_value(argc, argv, i));
        } else if (arg == "--seed") {
            params.seed = static_cast<unsigned>(std::strtoul(require_value(argc, argv, i), nullptr, 10));
        } else if (arg == "--report") {
            params.report_every = std::atoi(require_value(argc, argv, i));
        } else if (arg == "--sample") {
            params.sample_every = std::atoi(require_value(argc, argv, i));
        } else if (arg == "--no-cells") {
            params.disable_cells = true;
        } else if (arg == "--rdf") {
            params.rdf_path = require_value(argc, argv, i);
        } else if (arg == "--traj") {
            params.traj_path = require_value(argc, argv, i);
        } else if (arg == "--thermostat") {
            const std::string value = require_value(argc, argv, i);
            if (value == "none") {
                params.thermostat = Params::Thermostat::None;
            } else if (value == "berendsen") {
                params.thermostat = Params::Thermostat::Berendsen;
            } else if (value == "langevin") {
                params.thermostat = Params::Thermostat::Langevin;
            } else {
                std::cerr << "error: unknown thermostat '" << value << "'\n";
                return 2;
            }
        } else {
            std::cerr << "error: unknown option '" << arg << "' (try --help)\n";
            return 2;
        }
    }

    if (params.report_every <= 0) params.report_every = 1;
    if (params.sample_every <= 0) params.sample_every = 1;

    try {
        Simulation sim(params);
        sim.run(std::cout);
    } catch (const std::exception& e) {
        std::cerr << "error: " << e.what() << "\n";
        return 1;
    }
    return 0;
}
