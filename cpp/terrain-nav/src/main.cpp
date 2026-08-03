#include <cstdlib>
#include <exception>
#include <iomanip>
#include <iostream>
#include <string>

#include "dem.hpp"
#include "navsim.hpp"
#include "particle_filter.hpp"
#include "render.hpp"

namespace {

void print_usage(const char* argv0) {
    std::cout <<
        "Terrain-referenced navigation: localise without GPS by matching a radar\n"
        "altimeter profile against a stored elevation map.\n\n"
        "usage: " << argv0 << " [options]\n\n"
        "terrain\n"
        "  --terrain KIND     fractal | ridged | flat | mixed      (default ridged)\n"
        "  --dem-size N       synthetic DEM side in samples        (default 1200)\n"
        "  --dem-spacing X    metres between samples               (default 30)\n"
        "  --hgt PATH         load a real SRTM .hgt tile instead\n"
        "  --terrain-seed N   synthetic terrain seed               (default 1)\n\n"
        "flight\n"
        "  --speed X          ground speed, m/s                    (default 120)\n"
        "  --heading X        degrees, 0 = east                    (default 20)\n"
        "  --duration X       seconds of flight                    (default 260)\n"
        "  --dt X             seconds between fixes                (default 1)\n"
        "  --start X,Y        initial true position, metres        (default 2500,2500)\n\n"
        "sensors\n"
        "  --radar-sigma X    radar altimeter noise, m             (default 3)\n"
        "  --baro-sigma X     barometric noise, m                  (default 9)\n"
        "  --ins-bias X       inertial velocity bias, m/s          (default 1.2)\n\n"
        "filter\n"
        "  --particles N      particle count                       (default 5000)\n"
        "  --init-radius X    initial position uncertainty, m      (default 1500)\n"
        "  --meas-sigma X     assumed elevation noise, m           (default 10)\n"
        "  --process-noise X  per-step position process noise, m   (default 12)\n"
        "  --seed N           run seed                             (default 7)\n\n"
        "output\n"
        "  --csv PATH         per-step history as CSV\n"
        "  --image PATH       hill-shaded map with tracks (PPM)\n"
        "  --quiet            summary only\n"
        "  --help\n";
}

const char* require_value(int argc, char** argv, int& i) {
    if (i + 1 >= argc) {
        std::cerr << "error: " << argv[i] << " needs a value\n";
        std::exit(2);
    }
    return argv[++i];
}

}  // namespace

int main(int argc, char** argv) {
    ScenarioConfig scenario;
    PfConfig pf;
    std::string terrain_kind = "ridged";
    std::string hgt_path, csv_path, image_path;
    int dem_size = 1200;
    double dem_spacing = 30.0;
    bool spacing_set = false;
    unsigned terrain_seed = 1;
    bool quiet = false;

    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--help" || arg == "-h") { print_usage(argv[0]); return 0; }
        else if (arg == "--terrain")       terrain_kind = require_value(argc, argv, i);
        else if (arg == "--dem-size")      dem_size = std::atoi(require_value(argc, argv, i));
        else if (arg == "--dem-spacing") {
            dem_spacing = std::atof(require_value(argc, argv, i));
            spacing_set = true;
        }
        else if (arg == "--hgt")           hgt_path = require_value(argc, argv, i);
        else if (arg == "--terrain-seed")  terrain_seed = static_cast<unsigned>(std::atoi(require_value(argc, argv, i)));
        else if (arg == "--speed")         scenario.speed = std::atof(require_value(argc, argv, i));
        else if (arg == "--heading")       scenario.heading_deg = std::atof(require_value(argc, argv, i));
        else if (arg == "--duration")      scenario.duration = std::atof(require_value(argc, argv, i));
        else if (arg == "--dt")            scenario.dt = std::atof(require_value(argc, argv, i));
        else if (arg == "--radar-sigma")   scenario.radar_sigma = std::atof(require_value(argc, argv, i));
        else if (arg == "--baro-sigma")    scenario.baro_sigma = std::atof(require_value(argc, argv, i));
        else if (arg == "--ins-bias")      scenario.ins_bias = std::atof(require_value(argc, argv, i));
        else if (arg == "--particles")     pf.count = std::atoi(require_value(argc, argv, i));
        else if (arg == "--init-radius")   pf.init_radius = std::atof(require_value(argc, argv, i));
        else if (arg == "--meas-sigma")    pf.meas_sigma = std::atof(require_value(argc, argv, i));
        else if (arg == "--process-noise") pf.process_noise = std::atof(require_value(argc, argv, i));
        else if (arg == "--seed")          scenario.seed = std::strtoull(require_value(argc, argv, i), nullptr, 10);
        else if (arg == "--csv")           csv_path = require_value(argc, argv, i);
        else if (arg == "--image")         image_path = require_value(argc, argv, i);
        else if (arg == "--quiet")         quiet = true;
        else if (arg == "--start") {
            const std::string v = require_value(argc, argv, i);
            const auto comma = v.find(',');
            if (comma == std::string::npos) {
                std::cerr << "error: --start expects X,Y\n";
                return 2;
            }
            scenario.start_x = std::atof(v.substr(0, comma).c_str());
            scenario.start_y = std::atof(v.substr(comma + 1).c_str());
        } else {
            std::cerr << "error: unknown option '" << arg << "' (try --help)\n";
            return 2;
        }
    }

    try {
        // For a real tile, only override the spacing if the user actually asked;
        // otherwise let the loader derive it from the filename's latitude.
        const Dem dem = hgt_path.empty()
            ? Dem::synthetic(dem_size, dem_size, dem_spacing, terrain_seed, terrain_kind)
            : Dem::from_hgt(hgt_path, spacing_set ? dem_spacing : 0.0);

        std::ostream& out = std::cout;
        out << std::fixed << std::setprecision(1);
        out << "terrain      " << (hgt_path.empty() ? terrain_kind : hgt_path) << "\n"
            << "grid         " << dem.width() << " x " << dem.height()
            << " at " << dem.spacing() << " m  ("
            << dem.extent_x() / 1000.0 << " x " << dem.extent_y() / 1000.0 << " km)\n"
            << "elevation    " << dem.min_elevation() << " to " << dem.max_elevation() << " m\n"
            << "particles    " << pf.count << "\n"
            << "initial box  +/- " << pf.init_radius << " m\n";

        NavSim sim(dem, scenario, pf);
        out << "flight       " << scenario.speed << " m/s at " << scenario.heading_deg
            << " deg, " << sim.altitude() << " m MSL\n";

        const RunSummary summary = sim.run(quiet ? nullptr : &out);

        out << "\nresult\n"
            << "  dead reckoning final error   " << summary.final_dr_error << " m"
            << "   (peak " << summary.max_dr_error << " m)\n"
            << "  terrain-aided final error    " << summary.final_pf_error << " m\n";

        if (!summary.ever_converged) {
            out << "  never acquired a fix (spread threshold " << summary.spread_threshold << " m)\n"
                << "  the terrain carries too little information to localise against\n";
        } else {
            out << "  acquired fix at              " << summary.first_converge_time << " s\n"
                << "  mean error while holding it  " << summary.mean_error_while_converged << " m\n"
                << "  fix held for                 " << 100.0 * summary.fraction_converged
                << " % of the flight\n";
            if (summary.lost_fix) {
                out << "  LOST fix at                  " << summary.lost_fix_time
                    << " s, where local roughness was only " << summary.roughness_at_loss << " m\n"
                    << "  the map stopped being distinctive — this is an observability\n"
                    << "  failure, not a filter bug\n";
            }
        }

        if (!csv_path.empty()) {
            write_history_csv(sim.history(), csv_path);
            out << "\nwrote " << csv_path << "\n";
        }
        if (!image_path.empty()) {
            render_map(dem, sim.history(), sim.filter(), image_path);
            out << "wrote " << image_path
                << "  (black = truth, red = dead reckoning, cyan = terrain-aided)\n";
        }
    } catch (const std::exception& e) {
        std::cerr << "error: " << e.what() << "\n";
        return 1;
    }
    return 0;
}
