#include "simulation.hpp"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>

namespace {

constexpr double kPi = 3.14159265358979323846;

// The 13 "forward" neighbour cells. Together with the i<j pairs inside a cell
// this visits every neighbouring pair exactly once.
constexpr int kHalfNeighbors[13][3] = {
    { 1,  0,  0}, { 1,  1,  0}, { 0,  1,  0}, {-1,  1,  0},
    { 0,  0,  1}, { 1,  0,  1}, { 1,  1,  1}, { 0,  1,  1},
    {-1,  1,  1}, {-1,  0,  1}, {-1, -1,  1}, { 0, -1,  1},
    { 1, -1,  1},
};

int wrap_index(int i, int n) {
    if (i < 0)  return i + n;
    if (i >= n) return i - n;
    return i;
}

}  // namespace

void Accumulator::add(double x) {
    ++n_;
    const double delta = x - mean_;
    mean_ += delta / static_cast<double>(n_);
    m2_ += delta * (x - mean_);
}

double Accumulator::stddev() const {
    if (n_ < 2) return 0.0;
    return std::sqrt(m2_ / static_cast<double>(n_ - 1));
}

Simulation::Simulation(const Params& params)
    : params_(params), rng_(params.seed) {
    if (params_.cells_per_side < 1) {
        throw std::invalid_argument("cells_per_side must be >= 1");
    }
    if (params_.density <= 0.0) {
        throw std::invalid_argument("density must be > 0");
    }

    const int n_cells = params_.cells_per_side;
    n_ = 4 * n_cells * n_cells * n_cells;          // 4 atoms per FCC conventional cell
    volume_ = static_cast<double>(n_) / params_.density;
    box_ = std::cbrt(volume_);

    if (box_ < 2.0 * params_.cutoff) {
        throw std::invalid_argument(
            "box is smaller than twice the cutoff — minimum image would be ambiguous; "
            "increase --cells or lower --cutoff");
    }

    cutoff2_ = params_.cutoff * params_.cutoff;

    const double inv_rc3 = 1.0 / (params_.cutoff * params_.cutoff * params_.cutoff);
    const double inv_rc6 = inv_rc3 * inv_rc3;
    const double inv_rc9 = inv_rc6 * inv_rc3;
    const double inv_rc12 = inv_rc6 * inv_rc6;
    energy_shift_ = 4.0 * (inv_rc12 - inv_rc6);

    // Standard long-range corrections for the tail beyond the cutoff, assuming
    // g(r) = 1 there. These are constants: they shift energies but never affect
    // the dynamics, so energy conservation is unchanged.
    energy_tail_ = (8.0 / 3.0) * kPi * n_ * params_.density * (inv_rc9 / 3.0 - inv_rc3);
    pressure_tail_ = (16.0 / 3.0) * kPi * params_.density * params_.density *
                     (2.0 * inv_rc9 / 3.0 - inv_rc3);

    positions_.resize(n_);
    velocities_.resize(n_);
    forces_.resize(n_);
    next_.resize(n_, -1);
    rdf_hist_.assign(static_cast<std::size_t>(params_.rdf_bins), 0.0);

    cells_side_ = static_cast<int>(std::floor(box_ / params_.cutoff));
    // Below 3 cells per side a cell's +1 and -1 neighbours are the same cell,
    // which would double-count those pairs.
    use_cells_ = cells_side_ >= 3 && !params_.disable_cells;
    if (use_cells_) {
        cell_size_ = box_ / cells_side_;
        head_.assign(static_cast<std::size_t>(cells_side_) * cells_side_ * cells_side_, -1);
    }

    init_fcc_lattice();
    init_velocities();
    compute_forces();
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

void Simulation::init_fcc_lattice() {
    // FCC basis inside one conventional cube of side a.
    const Vec3 basis[4] = {
        {0.0, 0.0, 0.0},
        {0.5, 0.5, 0.0},
        {0.5, 0.0, 0.5},
        {0.0, 0.5, 0.5},
    };

    const int n_cells = params_.cells_per_side;
    const double a = box_ / n_cells;

    int index = 0;
    for (int ix = 0; ix < n_cells; ++ix) {
        for (int iy = 0; iy < n_cells; ++iy) {
            for (int iz = 0; iz < n_cells; ++iz) {
                for (const Vec3& b : basis) {
                    positions_[index].x = (ix + b.x) * a;
                    positions_[index].y = (iy + b.y) * a;
                    positions_[index].z = (iz + b.z) * a;
                    ++index;
                }
            }
        }
    }
}

void Simulation::init_velocities() {
    // Maxwell-Boltzmann: each Cartesian component is Gaussian with variance
    // k_B T / m, which is just T in reduced units with m = 1.
    std::normal_distribution<double> gauss(0.0, std::sqrt(params_.temperature));
    for (Vec3& v : velocities_) {
        v = {gauss(rng_), gauss(rng_), gauss(rng_)};
    }

    // Remove net drift; otherwise the centre of mass sails across the box and
    // its kinetic energy pollutes the temperature.
    Vec3 total{};
    for (const Vec3& v : velocities_) total += v;
    total *= 1.0 / n_;
    for (Vec3& v : velocities_) v -= total;

    // Rescale so the starting temperature is exactly the requested one.
    const double current = instantaneous_temperature();
    if (current > 0.0) {
        const double scale = std::sqrt(params_.temperature / current);
        for (Vec3& v : velocities_) v *= scale;
    }
}

// ---------------------------------------------------------------------------
// Geometry
// ---------------------------------------------------------------------------

Vec3 Simulation::minimum_image(Vec3 d) const {
    d.x -= box_ * std::nearbyint(d.x / box_);
    d.y -= box_ * std::nearbyint(d.y / box_);
    d.z -= box_ * std::nearbyint(d.z / box_);
    return d;
}

void Simulation::wrap_into_box(Vec3& r) const {
    r.x -= box_ * std::floor(r.x / box_);
    r.y -= box_ * std::floor(r.y / box_);
    r.z -= box_ * std::floor(r.z / box_);
}

// ---------------------------------------------------------------------------
// Forces
// ---------------------------------------------------------------------------

void Simulation::accumulate_pair(int i, int j) {
    const Vec3 d = minimum_image(positions_[i] - positions_[j]);
    const double r2 = norm2(d);
    if (r2 >= cutoff2_) return;

    // U(r)     = 4 (r^-12 - r^-6)
    // F(r)/r   = 24 (2 r^-12 - r^-6) / r^2
    const double inv_r2  = 1.0 / r2;
    const double inv_r6  = inv_r2 * inv_r2 * inv_r2;
    const double inv_r12 = inv_r6 * inv_r6;

    const double f_over_r = 24.0 * (2.0 * inv_r12 - inv_r6) * inv_r2;
    const Vec3 f = f_over_r * d;

    forces_[i] += f;
    forces_[j] -= f;                       // Newton's third law: one evaluation, two atoms
    potential_ += 4.0 * (inv_r12 - inv_r6) - energy_shift_;
    virial_ += f_over_r * r2;              // == dot(d, f)
}

void Simulation::build_cell_list() {
    std::fill(head_.begin(), head_.end(), -1);
    for (int i = 0; i < n_; ++i) {
        int ix = static_cast<int>(positions_[i].x / cell_size_);
        int iy = static_cast<int>(positions_[i].y / cell_size_);
        int iz = static_cast<int>(positions_[i].z / cell_size_);
        // Guard against atoms sitting exactly on the far face after rounding.
        ix = std::min(std::max(ix, 0), cells_side_ - 1);
        iy = std::min(std::max(iy, 0), cells_side_ - 1);
        iz = std::min(std::max(iz, 0), cells_side_ - 1);

        const int c = (ix * cells_side_ + iy) * cells_side_ + iz;
        next_[i] = head_[c];
        head_[c] = i;
    }
}

void Simulation::compute_forces() {
    std::fill(forces_.begin(), forces_.end(), Vec3{});
    potential_ = 0.0;
    virial_ = 0.0;

    if (use_cells_) {
        compute_forces_cells();
    } else {
        compute_forces_brute();
    }
}

void Simulation::compute_forces_brute() {
    for (int i = 0; i < n_; ++i) {
        for (int j = i + 1; j < n_; ++j) {
            accumulate_pair(i, j);
        }
    }
}

void Simulation::compute_forces_cells() {
    build_cell_list();

    for (int ix = 0; ix < cells_side_; ++ix) {
        for (int iy = 0; iy < cells_side_; ++iy) {
            for (int iz = 0; iz < cells_side_; ++iz) {
                const int c = (ix * cells_side_ + iy) * cells_side_ + iz;

                // Pairs wholly inside this cell.
                for (int i = head_[c]; i >= 0; i = next_[i]) {
                    for (int j = next_[i]; j >= 0; j = next_[j]) {
                        accumulate_pair(i, j);
                    }
                }

                // Pairs spanning this cell and one of its 13 forward neighbours.
                for (const auto& off : kHalfNeighbors) {
                    const int jx = wrap_index(ix + off[0], cells_side_);
                    const int jy = wrap_index(iy + off[1], cells_side_);
                    const int jz = wrap_index(iz + off[2], cells_side_);
                    const int cn = (jx * cells_side_ + jy) * cells_side_ + jz;

                    for (int i = head_[c]; i >= 0; i = next_[i]) {
                        for (int j = head_[cn]; j >= 0; j = next_[j]) {
                            accumulate_pair(i, j);
                        }
                    }
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Integration
// ---------------------------------------------------------------------------

void Simulation::step_velocity_verlet() {
    const double dt = params_.dt;
    const double half = 0.5 * dt;

    for (int i = 0; i < n_; ++i) {
        velocities_[i] += half * forces_[i];          // m = 1
        positions_[i] += dt * velocities_[i];
        wrap_into_box(positions_[i]);
    }

    compute_forces();

    for (int i = 0; i < n_; ++i) {
        velocities_[i] += half * forces_[i];
    }
}

void Simulation::ornstein_uhlenbeck(double dt) {
    const double c1 = std::exp(-params_.friction * dt);
    const double c2 = std::sqrt((1.0 - c1 * c1) * params_.temperature);  // m = 1
    std::normal_distribution<double> gauss(0.0, 1.0);

    for (Vec3& v : velocities_) {
        v.x = c1 * v.x + c2 * gauss(rng_);
        v.y = c1 * v.y + c2 * gauss(rng_);
        v.z = c1 * v.z + c2 * gauss(rng_);
    }
}

void Simulation::step_baoab() {
    // BAOAB Langevin splitting: the best-behaved of the common orderings for
    // configurational averages, and it samples the canonical ensemble.
    const double dt = params_.dt;
    const double half = 0.5 * dt;

    for (int i = 0; i < n_; ++i) velocities_[i] += half * forces_[i];      // B
    for (int i = 0; i < n_; ++i) positions_[i] += half * velocities_[i];   // A

    ornstein_uhlenbeck(dt);                                                // O

    for (int i = 0; i < n_; ++i) {                                         // A
        positions_[i] += half * velocities_[i];
        wrap_into_box(positions_[i]);
    }

    compute_forces();

    for (int i = 0; i < n_; ++i) velocities_[i] += half * forces_[i];      // B
}

void Simulation::apply_berendsen(double current_temperature) {
    if (current_temperature <= 0.0) return;
    // Weak coupling: gentle, robust, and fine for equilibration — but it does
    // NOT sample a correct canonical ensemble, so we only use it before
    // production and switch to NVE (or Langevin) to measure.
    const double ratio = params_.temperature / current_temperature;
    const double lambda = std::sqrt(1.0 + (params_.dt / params_.tau) * (ratio - 1.0));
    for (Vec3& v : velocities_) v *= lambda;
}

// ---------------------------------------------------------------------------
// Measurement
// ---------------------------------------------------------------------------

double Simulation::kinetic_energy() const {
    double sum = 0.0;
    for (const Vec3& v : velocities_) sum += norm2(v);
    return 0.5 * sum;   // m = 1
}

double Simulation::instantaneous_temperature() const {
    // 3N - 3 degrees of freedom, because we froze the centre-of-mass motion.
    const double dof = 3.0 * n_ - 3.0;
    return 2.0 * kinetic_energy() / dof;
}

Observables Simulation::measure() const {
    const double ke = kinetic_energy();
    const double pe = potential_ + energy_tail_;
    const double temperature = instantaneous_temperature();

    Observables obs;
    obs.kinetic = ke / n_;
    obs.potential = pe / n_;
    obs.total = (ke + pe) / n_;
    obs.temperature = temperature;
    obs.pressure = params_.density * temperature + virial_ / (3.0 * volume_) + pressure_tail_;
    return obs;
}

void Simulation::accumulate_rdf() {
    // Sampled out to L/2 — the largest distance the minimum-image convention
    // can represent unambiguously — so this needs its own O(N^2) sweep rather
    // than reusing the cutoff neighbour list.
    const double r_max = 0.5 * box_;
    const double bin_width = r_max / params_.rdf_bins;

    for (int i = 0; i < n_; ++i) {
        for (int j = i + 1; j < n_; ++j) {
            const double r = norm(minimum_image(positions_[i] - positions_[j]));
            if (r >= r_max) continue;
            const auto bin = static_cast<std::size_t>(r / bin_width);
            if (bin < rdf_hist_.size()) rdf_hist_[bin] += 2.0;   // i-j and j-i
        }
    }
    ++rdf_frames_;
}

void Simulation::write_rdf(const std::string& path) const {
    if (rdf_frames_ == 0) return;

    std::ofstream out(path);
    if (!out) {
        std::cerr << "warning: could not open " << path << " for writing\n";
        return;
    }

    const double r_max = 0.5 * box_;
    const double bin_width = r_max / params_.rdf_bins;

    out << "# r  g(r)\n";
    out << std::fixed << std::setprecision(6);
    for (int b = 0; b < params_.rdf_bins; ++b) {
        const double r_lo = b * bin_width;
        const double r_hi = r_lo + bin_width;
        const double shell = (4.0 / 3.0) * kPi * (r_hi * r_hi * r_hi - r_lo * r_lo * r_lo);
        // Expected count in the shell for an ideal gas at the same density.
        const double ideal = shell * params_.density * n_ * rdf_frames_;
        out << 0.5 * (r_lo + r_hi) << "  " << rdf_hist_[b] / ideal << "\n";
    }
}

void Simulation::write_xyz(std::ostream& os, long step) const {
    os << n_ << "\n";
    os << "step " << step << " box " << box_ << "\n";
    os << std::fixed << std::setprecision(5);
    for (const Vec3& r : positions_) {
        os << "Ar  " << r.x << ' ' << r.y << ' ' << r.z << "\n";
    }
}

// ---------------------------------------------------------------------------
// Driver
// ---------------------------------------------------------------------------

void Simulation::run(std::ostream& log) {
    log << std::fixed;
    log << "atoms            " << n_ << "\n"
        << "box length       " << std::setprecision(4) << box_ << " sigma\n"
        << "density          " << params_.density << "\n"
        << "target T         " << params_.temperature << "\n"
        << "timestep         " << std::setprecision(4) << params_.dt << "\n"
        << "cutoff           " << params_.cutoff << "\n"
        << "neighbour search " << (use_cells_ ? "cell list" : "all pairs")
        << (use_cells_ ? " (" + std::to_string(cells_side_) + "^3 cells)" : "") << "\n\n";

    // ---- equilibration -----------------------------------------------------
    log << "equilibrating for " << params_.equil_steps << " steps\n";
    log << std::setw(10) << "step" << std::setw(12) << "T"
        << std::setw(14) << "E/atom" << "\n";

    for (long step = 1; step <= params_.equil_steps; ++step) {
        if (params_.thermostat == Params::Thermostat::Langevin) {
            step_baoab();
        } else {
            step_velocity_verlet();
            if (params_.thermostat == Params::Thermostat::Berendsen) {
                apply_berendsen(instantaneous_temperature());
            }
        }

        if (step % params_.report_every == 0) {
            const Observables o = measure();
            log << std::setw(10) << step
                << std::setw(12) << std::setprecision(4) << o.temperature
                << std::setw(14) << std::setprecision(5) << o.total << "\n";
        }
    }

    // ---- production --------------------------------------------------------
    // The thermostat is off unless Langevin was requested: constant-energy
    // dynamics is what lets us check the integrator with energy conservation.
    const bool nve = params_.thermostat != Params::Thermostat::Langevin;

    log << "\nproduction for " << params_.prod_steps << " steps ("
        << (nve ? "NVE" : "NVT/Langevin") << ")\n";
    log << std::setw(10) << "step" << std::setw(12) << "T"
        << std::setw(14) << "PE/atom" << std::setw(14) << "E/atom"
        << std::setw(12) << "P" << "\n";

    const Observables initial = measure();
    const double e0 = initial.total;
    double max_drift = 0.0;

    Accumulator temperature_acc, potential_acc, pressure_acc, total_acc;

    std::ofstream traj;
    if (!params_.traj_path.empty()) {
        traj.open(params_.traj_path);
        if (!traj) std::cerr << "warning: could not open " << params_.traj_path << "\n";
    }

    for (long step = 1; step <= params_.prod_steps; ++step) {
        if (nve) {
            step_velocity_verlet();
        } else {
            step_baoab();
        }

        if (step % params_.sample_every == 0) {
            const Observables o = measure();
            temperature_acc.add(o.temperature);
            potential_acc.add(o.potential);
            pressure_acc.add(o.pressure);
            total_acc.add(o.total);
            accumulate_rdf();

            max_drift = std::max(max_drift, std::abs((o.total - e0) / e0));

            if (traj) write_xyz(traj, step);
        }

        if (step % params_.report_every == 0) {
            const Observables o = measure();
            log << std::setw(10) << step
                << std::setw(12) << std::setprecision(4) << o.temperature
                << std::setw(14) << std::setprecision(5) << o.potential
                << std::setw(14) << std::setprecision(5) << o.total
                << std::setw(12) << std::setprecision(4) << o.pressure << "\n";
        }
    }

    // ---- summary -----------------------------------------------------------
    log << "\naverages over " << total_acc.count() << " samples\n"
        << "  T           " << std::setprecision(4) << temperature_acc.mean()
        << " +/- " << temperature_acc.stddev() << "\n"
        << "  PE/atom     " << std::setprecision(4) << potential_acc.mean()
        << " +/- " << potential_acc.stddev() << "\n"
        << "  E/atom      " << std::setprecision(4) << total_acc.mean()
        << " +/- " << total_acc.stddev() << "\n"
        << "  P           " << std::setprecision(4) << pressure_acc.mean()
        << " +/- " << pressure_acc.stddev() << "\n";

    if (nve) {
        log << "\nenergy conservation (the integrator's report card)\n"
            << "  max |dE/E|  " << std::scientific << std::setprecision(3) << max_drift
            << std::fixed << "\n";
    }

    // Argon: sigma = 3.405 A, eps/kB = 119.8 K, m = 39.948 u
    //        => tau = sigma sqrt(m/eps) = 2.156 ps, P unit = 41.9 MPa
    log << "\nsame state point, mapped onto argon\n"
        << "  T           " << std::setprecision(1) << temperature_acc.mean() * 119.8 << " K\n"
        << "  P           " << std::setprecision(1) << pressure_acc.mean() * 41.9 << " MPa\n"
        << "  box         " << std::setprecision(2) << box_ * 3.405 << " A\n"
        << "  simulated   " << std::setprecision(1)
        << params_.prod_steps * params_.dt * 2.156 << " ps\n";

    if (!params_.rdf_path.empty()) {
        write_rdf(params_.rdf_path);
        log << "\nwrote g(r) to " << params_.rdf_path << "\n";
    }
    if (traj) {
        log << "wrote trajectory to " << params_.traj_path << "\n";
    }
}
