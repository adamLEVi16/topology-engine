#pragma once

#include <string>
#include <vector>

// A digital elevation model: a regular grid of ground heights in metres.
//
// Coordinates are a local east-north-up frame, also in metres, with the origin
// at grid node (0, 0). x runs east along columns, y runs north along rows, so
// node (i, j) sits at (i * spacing, j * spacing).
class Dem {
public:
    // Procedurally generated terrain, so the whole thing runs with no downloads.
    //   "fractal" — fractional Brownian motion, rolling hills
    //   "ridged"  — sharper ridges and valleys, very informative for navigation
    //   "flat"    — near-featureless plain, the pathological case
    //   "mixed"   — ridged terrain that fades into a plain partway across, so a
    //               single flight can show the filter converging and then losing
    //               its fix as the terrain stops being informative
    static Dem synthetic(int width, int height, double spacing,
                         unsigned seed, const std::string& kind);

    // SRTM .hgt: a square grid of big-endian int16 metres, row 0 northernmost.
    // The side length is implied by the file size (1201 for 3-arcsecond data,
    // 3601 for 1-arcsecond). Spacing is derived from the latitude encoded in
    // the filename unless spacing_override is positive.
    static Dem from_hgt(const std::string& path, double spacing_override = 0.0);

    // Bilinear interpolation. Queries outside the grid clamp to the edge.
    double elevation(double x, double y) const;
    bool in_bounds(double x, double y) const;

    int width() const { return w_; }
    int height() const { return h_; }
    double spacing() const { return spacing_; }
    double extent_x() const { return (w_ - 1) * spacing_; }
    double extent_y() const { return (h_ - 1) * spacing_; }

    double at(int i, int j) const { return z_[static_cast<std::size_t>(j) * w_ + i]; }
    double min_elevation() const { return min_z_; }
    double max_elevation() const { return max_z_; }

    // Standard deviation of elevation inside a square window. This is the
    // cheapest useful proxy for how much navigation information the terrain
    // carries locally — see the README on observability.
    double roughness(double x, double y, double window) const;

private:
    void recompute_bounds();

    int w_ = 0;
    int h_ = 0;
    double spacing_ = 0.0;
    double min_z_ = 0.0;
    double max_z_ = 0.0;
    std::vector<float> z_;
};
