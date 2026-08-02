#pragma once

#include <cstdint>
#include <iosfwd>
#include <random>
#include <vector>

#include "params.hpp"
#include "vec3.hpp"

struct Observables {
    double kinetic     = 0.0;  // per atom
    double potential   = 0.0;  // per atom, tail-corrected
    double total       = 0.0;  // per atom
    double temperature = 0.0;
    double pressure    = 0.0;  // tail-corrected
};

// Running mean/stddev without storing the samples.
class Accumulator {
public:
    void add(double x);
    double mean() const { return mean_; }
    double stddev() const;
    long count() const { return n_; }

private:
    long   n_    = 0;
    double mean_ = 0.0;
    double m2_   = 0.0;
};

class Simulation {
public:
    explicit Simulation(const Params& params);

    void run(std::ostream& log);

    int    atom_count() const { return n_; }
    double box_length() const { return box_; }

private:
    // --- setup ---
    void init_fcc_lattice();
    void init_velocities();

    // --- forces ---
    void compute_forces();                       // dispatches on cell-list validity
    void compute_forces_cells();
    void compute_forces_brute();
    void accumulate_pair(int i, int j);           // shared inner kernel
    void build_cell_list();

    // --- integration ---
    void step_velocity_verlet();
    void step_baoab();                            // Langevin, samples NVT
    void apply_berendsen(double current_temperature);
    void ornstein_uhlenbeck(double dt);

    // --- measurement ---
    Observables measure() const;
    double kinetic_energy() const;
    double instantaneous_temperature() const;
    void accumulate_rdf();
    void write_rdf(const std::string& path) const;
    void write_xyz(std::ostream& os, long step) const;

    // --- geometry helpers ---
    Vec3 minimum_image(Vec3 d) const;
    void wrap_into_box(Vec3& r) const;

    Params params_;
    int    n_   = 0;
    double box_ = 0.0;
    double volume_ = 0.0;

    double cutoff2_      = 0.0;
    double energy_shift_ = 0.0;  // U(rc), subtracted so the potential is continuous
    double energy_tail_  = 0.0;  // long-range correction, total (not per atom)
    double pressure_tail_ = 0.0;

    std::vector<Vec3> positions_;
    std::vector<Vec3> velocities_;
    std::vector<Vec3> forces_;

    double potential_ = 0.0;  // total, shifted, no tail correction
    double virial_    = 0.0;  // sum over pairs of r_ij . f_ij

    // Linked cell list. head_[c] is the first atom in cell c, next_[i] the next
    // atom in the same cell, or -1 to terminate.
    std::vector<int> head_;
    std::vector<int> next_;
    int    cells_side_ = 0;
    double cell_size_  = 0.0;
    bool   use_cells_  = false;

    std::vector<double> rdf_hist_;
    long rdf_frames_ = 0;

    std::mt19937_64 rng_;
};
