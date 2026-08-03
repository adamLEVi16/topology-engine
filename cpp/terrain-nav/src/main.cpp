#include <cstdlib>
#include <exception>
#include <iomanip>
#include <cmath>
#include <chrono>
#include <fstream>
#include <iostream>
#include <string>

#include <memory>

#include "dem.hpp"
#include "neural_map.hpp"
#include "perturbed_map.hpp"
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
        "  --terrain-seed N   synthetic terrain seed               (default 1)\n"
        "  --relief X         vertical relief of the terrain, m     (default 900)\n\n"
        "map error\n"
        "  --gradient-inflation  scale measurement variance by local slope\n"
        "  --map-shift X,Y    deliberate map misregistration, m     (default 0,0)\n"
        "  --map-h-sigma X    DEM horizontal accuracy, m            (default 12)\n"
        "  --map-v-sigma X    DEM vertical accuracy, m              (default 3)\n"
        "  --map-downsample N degrade the stored map by factor N   (default 1)\n"
        "  --map-interp MODE  bilinear | bicubic                    (default bilinear)\n"
        "  --neural PATH      navigate against a trained SIREN instead of a grid\n"
        "  --error-amplitude X  inject synthetic map error, RMS metres     (default 0)\n"
        "  --error-wavelength X spatial scale of the injected error, m     (default 500)\n"
        "  --error-aspect X     stretch error along x by X, along y by 1/X (default 1)\n"
        "  --error-seed N       injected error field seed                  (default 11)\n"
        "  --dump-dem PATH    write the truth grid as raw float32 and exit\n"
        "  --map-rmse         report map fidelity vs truth (elevation + gradient), then exit\n"
        "  --bench-map N      time N elevation and gradient queries, then exit\n"
        "  --probe X,Y        print map elevation and gradient at a point, then exit\n"
        "                     (compares the analytic gradient against finite differences)\n\n"
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
        "  --filter MODE      pf2d | pf4d | rbpf                   (default pf2d)\n"
        "                       pf2d  position only, bias absorbed into process noise\n"
        "                       pf4d  bootstrap over (x,y,bx,by), brute-force baseline\n"
        "                       rbpf  particles in (x,y) + a 2x2 Kalman filter per\n"
        "                             particle for the bias (Rao-Blackwellised)\n"
        "  --bias-prior X     initial bias uncertainty, m/s        (default 3)\n"
        "  --bias-walk X      bias random walk, m/s per step       (default 0.004)\n"
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
    double relief = 900.0;
    int map_downsample = 1;
    Dem::Interp map_interp = Dem::Interp::Bilinear;
    double err_amplitude = 0.0, err_wavelength = 500.0, err_aspect = 1.0;
    unsigned err_seed = 11;
    std::string neural_path, dump_path;
    double probe_x = 0.0, probe_y = 0.0;
    bool do_probe = false;
    bool do_rmse = false;
    std::string dump_map_path;
    long bench_queries = 0;
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
        else if (arg == "--relief")        relief = std::atof(require_value(argc, argv, i));
        else if (arg == "--gradient-inflation") pf.inflate_on_gradient = true;
        else if (arg == "--neural")        neural_path = require_value(argc, argv, i);
        else if (arg == "--error-amplitude")  err_amplitude = std::atof(require_value(argc, argv, i));
        else if (arg == "--error-wavelength") err_wavelength = std::atof(require_value(argc, argv, i));
        else if (arg == "--error-aspect")     err_aspect = std::atof(require_value(argc, argv, i));
        else if (arg == "--error-seed")       err_seed = static_cast<unsigned>(std::atoi(require_value(argc, argv, i)));
        else if (arg == "--dump-dem")      dump_path = require_value(argc, argv, i);
        else if (arg == "--map-rmse")      do_rmse = true;
        else if (arg == "--dump-map")      dump_map_path = require_value(argc, argv, i);
        else if (arg == "--bench-map")     bench_queries = std::atol(require_value(argc, argv, i));
        else if (arg == "--probe") {
            const std::string v = require_value(argc, argv, i);
            const auto comma = v.find(',');
            if (comma == std::string::npos) { std::cerr << "error: --probe expects X,Y\n"; return 2; }
            probe_x = std::atof(v.substr(0, comma).c_str());
            probe_y = std::atof(v.substr(comma + 1).c_str());
            do_probe = true;
        }
        else if (arg == "--map-interp") {
            const std::string v = require_value(argc, argv, i);
            if      (v == "bilinear") map_interp = Dem::Interp::Bilinear;
            else if (v == "bicubic")  map_interp = Dem::Interp::Bicubic;
            else { std::cerr << "error: --map-interp expects bilinear or bicubic\n"; return 2; }
        }
        else if (arg == "--map-downsample") map_downsample = std::atoi(require_value(argc, argv, i));
        else if (arg == "--map-h-sigma")   pf.map_horizontal_sigma = std::atof(require_value(argc, argv, i));
        else if (arg == "--map-v-sigma")   pf.map_vertical_sigma = std::atof(require_value(argc, argv, i));
        else if (arg == "--map-shift") {
            const std::string v = require_value(argc, argv, i);
            const auto comma = v.find(',');
            if (comma == std::string::npos) {
                std::cerr << "error: --map-shift expects X,Y\n";
                return 2;
            }
            pf.map_shift_x = std::atof(v.substr(0, comma).c_str());
            pf.map_shift_y = std::atof(v.substr(comma + 1).c_str());
        }
        else if (arg == "--bias-prior")    pf.bias_prior = std::atof(require_value(argc, argv, i));
        else if (arg == "--bias-walk")     pf.bias_walk = std::atof(require_value(argc, argv, i));
        else if (arg == "--particles")     pf.count = std::atoi(require_value(argc, argv, i));
        else if (arg == "--filter") {
            const std::string v = require_value(argc, argv, i);
            if      (v == "pf2d") pf.mode = FilterMode::Position2D;
            else if (v == "pf4d") pf.mode = FilterMode::Bootstrap4D;
            else if (v == "rbpf") pf.mode = FilterMode::RaoBlackwellized;
            else {
                std::cerr << "error: unknown filter '" << v << "' (pf2d, pf4d, rbpf)\n";
                return 2;
            }
        }
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
            ? Dem::synthetic(dem_size, dem_size, dem_spacing, terrain_seed, terrain_kind, relief)
            : Dem::from_hgt(hgt_path, spacing_set ? dem_spacing : 0.0);

        if (!dump_path.empty()) {
            std::ofstream raw(dump_path, std::ios::binary);
            if (!raw) { std::cerr << "error: cannot write " << dump_path << "\n"; return 1; }
            for (int j = 0; j < dem.height(); ++j) {
                for (int i2 = 0; i2 < dem.width(); ++i2) {
                    const auto v = static_cast<float>(dem.at(i2, j));
                    raw.write(reinterpret_cast<const char*>(&v), sizeof(v));
                }
            }
            std::cout << "wrote " << dump_path << "  (" << dem.width() << " x "
                      << dem.height() << " float32 @ " << dem.spacing() << " m)\n";
            return 0;
        }

        std::ostream& out = std::cout;
        out << std::fixed << std::setprecision(1);
        out << "terrain      " << (hgt_path.empty() ? terrain_kind : hgt_path) << "\n"
            << "grid         " << dem.width() << " x " << dem.height()
            << " at " << dem.spacing() << " m  ("
            << dem.extent_x() / 1000.0 << " x " << dem.extent_y() / 1000.0 << " km)\n"
            << "elevation    " << dem.min_elevation() << " to " << dem.max_elevation()
            << " m   (mean slope " << std::setprecision(3) << dem.mean_slope()
            << ", " << std::setprecision(1) << std::atan(dem.mean_slope()) * 180.0 / 3.14159265 << " deg)\n"
            << "particles    " << pf.count << "\n"
            << "initial box  +/- " << pf.init_radius << " m\n";

        // The stored map is a separate object from the ground truth: it may be
        // decimated, re-interpolated, or replaced by a neural field entirely.
        std::unique_ptr<Dem> grid_map;
        std::unique_ptr<NeuralMap> neural;
        std::unique_ptr<PerturbedMap> perturbed;
        const TerrainMap* map_ptr = nullptr;

        if (err_amplitude > 0.0) {
            // Wraps the exact truth grid, so injected error is the only difference.
            perturbed = std::make_unique<PerturbedMap>(dem, err_amplitude, err_wavelength,
                                                       err_aspect, err_seed);
            map_ptr = perturbed.get();
        } else if (!neural_path.empty()) {
            neural = std::make_unique<NeuralMap>(NeuralMap::load(neural_path));
            map_ptr = neural.get();
        } else {
            grid_map = std::make_unique<Dem>(map_downsample > 1 ? dem.downsample(map_downsample)
                                                                : dem);
            grid_map->set_interp(map_interp);
            map_ptr = grid_map.get();
        }

        out << "stored map   " << map_ptr->describe() << "   ("
            << map_ptr->memory_bytes() / 1024.0 << " KiB vs "
            << dem.memory_bytes() / 1024.0 << " KiB truth)\n";

        if (!dump_map_path.empty()) {
            // Sample whatever representation is loaded onto the truth grid, so
            // the error field can be analysed at the truth's own resolution.
            std::ofstream raw(dump_map_path, std::ios::binary);
            if (!raw) { std::cerr << "error: cannot write " << dump_map_path << "\n"; return 1; }
            for (int j = 0; j < dem.height(); ++j) {
                for (int i2 = 0; i2 < dem.width(); ++i2) {
                    const auto v = static_cast<float>(
                        map_ptr->elevation(i2 * dem.spacing(), j * dem.spacing()));
                    raw.write(reinterpret_cast<const char*>(&v), sizeof(v));
                }
            }
            std::cout << "wrote " << dump_map_path << "  (" << map_ptr->describe() << ")\n";
            return 0;
        }

        if (do_rmse) {
            // Sample on a stride offset from the grid nodes, so a grid map is
            // measured where it interpolates rather than only where it stores.
            double se = 0.0, sg = 0.0;
            long n = 0;
            const double step = dem.spacing() * 2.5;
            for (double y = step; y < dem.extent_y() - step; y += step) {
                for (double x = step; x < dem.extent_x() - step; x += step) {
                    const double de = map_ptr->elevation(x, y) - dem.elevation(x, y);
                    const Vec2 g1 = map_ptr->gradient(x, y);
                    const Vec2 g0 = dem.gradient(x, y);
                    se += de * de;
                    sg += (g1.x - g0.x) * (g1.x - g0.x) + (g1.y - g0.y) * (g1.y - g0.y);
                    ++n;
                }
            }
            // Two extra diagnostics, because elevation RMSE alone turns out not
            // to predict navigation performance at all.
            //  - mean |gradient| detects over-smoothing: a representation that
            //    reconstructs the big shapes but erases fine relief scores well
            //    on RMSE while destroying local distinctiveness.
            //  - the spread and tail of |error| detect spatially uneven error,
            //    which penalises particles differentially rather than in common.
            double sum_gm = 0.0, sum_gt = 0.0, sum_ae = 0.0, sum_ae2 = 0.0, max_ae = 0.0;
            for (double y = step; y < dem.extent_y() - step; y += step) {
                for (double x = step; x < dem.extent_x() - step; x += step) {
                    const Vec2 g1 = map_ptr->gradient(x, y);
                    const Vec2 g0 = dem.gradient(x, y);
                    sum_gm += std::sqrt(g1.x * g1.x + g1.y * g1.y);
                    sum_gt += std::sqrt(g0.x * g0.x + g0.y * g0.y);
                    const double ae = std::fabs(map_ptr->elevation(x, y) - dem.elevation(x, y));
                    sum_ae += ae; sum_ae2 += ae * ae; max_ae = std::max(max_ae, ae);
                }
            }
            const double mean_ae = sum_ae / n;
            out << std::setprecision(4)
                << "elevation RMSE   " << std::sqrt(se / n) << " m\n"
                << "gradient RMSE    " << std::sqrt(sg / n) << " (m/m)\n"
                << "mean |grad| map  " << sum_gm / n << "\n"
                << "mean |grad| truth " << sum_gt / n << "\n"
                << "relief retained  " << 100.0 * (sum_gm / sum_gt) << " %\n"
                << "error std/mean   " << std::sqrt(sum_ae2 / n - mean_ae * mean_ae) / mean_ae << "\n"
                << "error max        " << max_ae << " m\n"
                << "samples          " << n << "\n";
            return 0;
        }

        if (bench_queries > 0) {
            const auto t0 = std::chrono::steady_clock::now();
            double sink = 0.0;
            for (long q = 0; q < bench_queries; ++q) {
                const double x = std::fmod(q * 137.0, dem.extent_x() - 1.0);
                const double y = std::fmod(q * 211.0, dem.extent_y() - 1.0);
                sink += map_ptr->elevation(x, y);
                sink += map_ptr->gradient(x, y).x;
            }
            const auto t1 = std::chrono::steady_clock::now();
            const double ns = std::chrono::duration<double, std::nano>(t1 - t0).count() / bench_queries;
            out << std::setprecision(1) << "query cost       " << ns
                << " ns per elevation+gradient pair\n"
                << "(checksum " << std::setprecision(3) << sink << ")\n";
            return 0;
        }

        if (do_probe) {
            const double z = map_ptr->elevation(probe_x, probe_y);
            const Vec2 g = map_ptr->gradient(probe_x, probe_y);
            // Central differences as an independent check on the analytic path.
            const double h = 0.5;
            const double fx = (map_ptr->elevation(probe_x + h, probe_y) -
                               map_ptr->elevation(probe_x - h, probe_y)) / (2 * h);
            const double fy = (map_ptr->elevation(probe_x, probe_y + h) -
                               map_ptr->elevation(probe_x, probe_y - h)) / (2 * h);
            out << std::setprecision(6)
                << "probe        (" << probe_x << ", " << probe_y << ")\n"
                << "elevation    " << z << " m\n"
                << "gradient     analytic (" << g.x << ", " << g.y << ")\n"
                << "             finite   (" << fx << ", " << fy << ")\n"
                << "             delta    (" << (g.x - fx) << ", " << (g.y - fy) << ")\n";
            return 0;
        }

        NavSim sim(dem, *map_ptr, scenario, pf);
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
            if (pf.mode != FilterMode::Position2D) {
                out << "  true inertial bias           (" << std::setprecision(3)
                    << summary.true_bias.x << ", " << summary.true_bias.y << ") m/s\n"
                    << "  estimated bias               (" << summary.final_est_bias.x
                    << ", " << summary.final_est_bias.y << ") m/s\n"
                    << "  bias error                   " << summary.final_bias_error
                    << " m/s" << std::setprecision(1) << "\n";
            }
            if (summary.lost_fix) {
                out << "  LOST fix at                  " << summary.lost_fix_time
                    << " s, where local roughness was only " << summary.roughness_at_loss << " m\n"
                    << "  the map stopped being distinctive — this is an observability\n"
                    << "  failure, not a filter bug\n"
                    << "  coasted                      " << summary.coast_seconds
                    << " s afterwards, drifting " << std::setprecision(2)
                    << summary.coast_drift_rate << " m/s" << std::setprecision(1) << "\n";
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
