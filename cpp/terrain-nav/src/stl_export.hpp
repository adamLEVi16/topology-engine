#pragma once

#include <string>

#include "dem.hpp"

struct StlOptions {
    double width_mm      = 150.0;  // physical size of the long axis of the print
    double base_mm       = 3.0;    // solid slab under the lowest ground, for rigidity
    double exaggeration  = 1.0;    // vertical scale multiplier; 1.0 is true to scale
    int    max_samples   = 300;    // grid is decimated to this on the long axis
};

// Writes the DEM as a watertight binary STL: a heightmap surface, vertical
// skirts, and a flat base. Printable as-is.
//
// Returns the number of triangles written, and reports the physical relief so
// the vertical exaggeration can be judged before committing filament to it.
std::size_t write_stl(const Dem& dem, const std::string& path,
                      const StlOptions& options, std::ostream& log);
