#pragma once

#include <cstddef>
#include <string>
#include <vector>

#include "terrain_map.hpp"

// Terrain stored as a SIREN — a small sinusoidal coordinate network that maps
// (x, y) to elevation. Unlike a grid it is a genuine analytic function, so its
// gradient comes from the chain rule rather than from differencing neighbours,
// and it is smooth everywhere rather than only within a cell.
//
// Trained by tools/train_siren.py, which writes the binary format this reads.
class NeuralMap : public TerrainMap {
public:
    static NeuralMap load(const std::string& path);

    double elevation(double x, double y) const override;
    Vec2 gradient(double x, double y) const override;
    bool in_bounds(double x, double y) const override;

    double extent_x() const override { return extent_x_; }
    double extent_y() const override { return extent_y_; }
    std::size_t memory_bytes() const override { return parameter_count_ * sizeof(float); }
    std::string describe() const override;

    std::size_t parameter_count() const { return parameter_count_; }

private:
    // Shared core: evaluates the network and, when jacobian is non-null, the
    // exact derivative alongside it by forward-mode accumulation.
    double evaluate(double x, double y, Vec2* jacobian) const;

    struct Layer {
        int in = 0;
        int out = 0;
        double omega = 1.0;         // frequency scale; 0 marks the linear output layer
        std::vector<float> weight;  // row-major, out x in
        std::vector<float> bias;
    };

    std::vector<Layer> layers_;
    std::size_t parameter_count_ = 0;

    // Inputs are normalised to roughly [-1, 1] and the output is de-normalised,
    // which is what lets one network cover terrain of any extent and relief.
    double x_scale_ = 1.0, y_scale_ = 1.0;
    double z_scale_ = 1.0, z_offset_ = 0.0;
    double extent_x_ = 0.0, extent_y_ = 0.0;
};
