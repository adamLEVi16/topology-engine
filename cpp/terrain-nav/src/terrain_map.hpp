#pragma once

#include <cstddef>
#include <string>

#include "linalg2.hpp"

// What the filter actually needs from a map. Everything downstream queries
// terrain through this interface, so a sampled grid and a trained neural field
// are interchangeable and can be compared at equal storage cost.
class TerrainMap {
public:
    virtual ~TerrainMap() = default;

    virtual double elevation(double x, double y) const = 0;

    // Analytic gradient in metres per metre. Grids differentiate their
    // interpolant; a neural field differentiates the network itself.
    virtual Vec2 gradient(double x, double y) const = 0;

    virtual bool in_bounds(double x, double y) const = 0;
    virtual double extent_x() const = 0;
    virtual double extent_y() const = 0;

    // Payload size, for like-for-like storage comparisons.
    virtual std::size_t memory_bytes() const = 0;

    virtual std::string describe() const = 0;
};
