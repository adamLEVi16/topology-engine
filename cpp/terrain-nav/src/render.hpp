#pragma once

#include <string>
#include <vector>

#include "dem.hpp"
#include "navsim.hpp"
#include "particle_filter.hpp"

// Renders a hill-shaded map of the terrain with the true track, the inertial
// dead-reckoned track, the terrain-aided estimate, and the final particle
// cloud overlaid. Writes a binary PPM, which every image viewer and every
// image library reads without a dependency.
void render_map(const Dem& dem,
                const std::vector<StepRecord>& history,
                const ParticleFilter& filter,
                const std::string& path,
                int max_pixels = 1400);
