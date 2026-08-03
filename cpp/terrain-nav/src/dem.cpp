#include "dem.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <stdexcept>

namespace {

std::uint32_t hash_u32(std::uint32_t x) {
    x ^= x >> 16; x *= 0x7feb352dU;
    x ^= x >> 15; x *= 0x846ca68bU;
    x ^= x >> 16;
    return x;
}

// Deterministic pseudo-random value in [0, 1) at an integer lattice point.
double lattice_value(int ix, int iy, unsigned seed) {
    const auto h = hash_u32(static_cast<std::uint32_t>(ix) * 73856093u ^
                            static_cast<std::uint32_t>(iy) * 19349663u ^ seed);
    return h * (1.0 / 4294967296.0);
}

double smoothstep(double t) { return t * t * (3.0 - 2.0 * t); }

double value_noise(double x, double y, unsigned seed) {
    const int ix = static_cast<int>(std::floor(x));
    const int iy = static_cast<int>(std::floor(y));
    const double ux = smoothstep(x - ix);
    const double uy = smoothstep(y - iy);

    const double a = lattice_value(ix,     iy,     seed);
    const double b = lattice_value(ix + 1, iy,     seed);
    const double c = lattice_value(ix,     iy + 1, seed);
    const double d = lattice_value(ix + 1, iy + 1, seed);

    const double top = a + (b - a) * ux;
    const double bot = c + (d - c) * ux;
    return top + (bot - top) * uy;
}

// Fractional Brownian motion: octaves of value noise at doubling frequency and
// halving amplitude. Real terrain is roughly self-similar, which is why this
// looks convincing at every zoom level.
double fbm(double x, double y, int octaves, unsigned seed, bool ridged) {
    double sum = 0.0;
    double amplitude = 1.0;
    double frequency = 1.0;
    double norm = 0.0;

    for (int o = 0; o < octaves; ++o) {
        double n = value_noise(x * frequency, y * frequency, seed + o * 7919u);
        if (ridged) {
            n = 1.0 - std::fabs(2.0 * n - 1.0);   // fold to make creased ridges
            n *= n;
        }
        sum += amplitude * n;
        norm += amplitude;
        amplitude *= 0.5;
        frequency *= 2.0;
    }
    return sum / norm;
}

}  // namespace

Dem Dem::synthetic(int width, int height, double spacing,
                   unsigned seed, const std::string& kind, double relief_scale) {
    if (width < 2 || height < 2) throw std::invalid_argument("DEM must be at least 2x2");
    if (spacing <= 0.0) throw std::invalid_argument("DEM spacing must be positive");

    const bool ridged = (kind == "ridged" || kind == "mixed");
    const bool flat   = (kind == "flat");
    if (kind != "fractal" && kind != "ridged" && kind != "flat" && kind != "mixed") {
        throw std::invalid_argument("unknown terrain kind '" + kind + "'");
    }

    Dem dem;
    dem.w_ = width;
    dem.h_ = height;
    dem.spacing_ = spacing;
    dem.z_.resize(static_cast<std::size_t>(width) * height);

    // Roughly six noise cycles across the map, then 8 octaves of detail on top.
    const double scale = 6.0 / std::max(width, height);
    const double relief = flat ? (relief_scale / 75.0) : relief_scale;  // metres of vertical relief
    const double base = 300.0;

    for (int j = 0; j < height; ++j) {
        for (int i = 0; i < width; ++i) {
            double amplitude = 1.0;

            if (kind == "mixed") {
                // Informative terrain on the west side, fading to a plain on the
                // east so one flight crosses both regimes.
                const double u = static_cast<double>(i) / (width - 1);
                const double t = std::min(std::max((u - 0.40) / 0.20, 0.0), 1.0);
                amplitude = 1.0 - smoothstep(t) * 0.985;
            }

            const double n = fbm(i * scale, j * scale, 8, seed, ridged);
            dem.z_[static_cast<std::size_t>(j) * width + i] =
                static_cast<float>(base + relief * amplitude * n);
        }
    }

    dem.recompute_bounds();
    return dem;
}

Dem Dem::from_hgt(const std::string& path, double spacing_override) {
    std::ifstream in(path, std::ios::binary | std::ios::ate);
    if (!in) throw std::runtime_error("cannot open DEM file: " + path);

    const std::streamsize bytes = in.tellg();
    in.seekg(0);

    const auto samples = static_cast<std::size_t>(bytes / 2);
    const auto side = static_cast<int>(std::lround(std::sqrt(static_cast<double>(samples))));
    if (static_cast<std::size_t>(side) * side != samples || bytes % 2 != 0) {
        throw std::runtime_error(path + ": not a square 16-bit grid (size " +
                                 std::to_string(bytes) + " bytes)");
    }

    std::vector<char> raw(static_cast<std::size_t>(bytes));
    if (!in.read(raw.data(), bytes)) throw std::runtime_error("short read on " + path);

    Dem dem;
    dem.w_ = side;
    dem.h_ = side;
    dem.z_.resize(samples);

    // Big-endian int16, and .hgt stores the northernmost row first, so flip
    // vertically to put y increasing northward.
    int voids = 0;
    for (int row = 0; row < side; ++row) {
        const int j = side - 1 - row;
        for (int i = 0; i < side; ++i) {
            const std::size_t k = (static_cast<std::size_t>(row) * side + i) * 2;
            const auto hi = static_cast<std::int16_t>(static_cast<unsigned char>(raw[k]));
            const auto lo = static_cast<unsigned char>(raw[k + 1]);
            const auto v = static_cast<std::int16_t>((hi << 8) | lo);
            // -32768 marks a void; hold the previous sample rather than
            // punching a hole the filter would read as a cliff.
            float value = (v == -32768) ? 0.0f : static_cast<float>(v);
            if (v == -32768) {
                ++voids;
                if (i > 0) value = dem.z_[static_cast<std::size_t>(j) * side + (i - 1)];
            }
            dem.z_[static_cast<std::size_t>(j) * side + i] = value;
        }
    }
    if (voids > 0) {
        std::fprintf(stderr, "note: %s contained %d void samples, filled by nearest west neighbour\n",
                     path.c_str(), voids);
    }

    if (spacing_override > 0.0) {
        dem.spacing_ = spacing_override;
    } else {
        // 1 arcsecond of latitude is ~30.87 m. Longitude shrinks by cos(lat),
        // so take the mean of the two axes from the latitude in the filename
        // (e.g. N37W122.hgt) and fall back to the equatorial value.
        const double arcsec = (side >= 3000) ? 1.0 : 3.0;
        double latitude = 0.0;
        const auto slash = path.find_last_of("/\\");
        const std::string name = (slash == std::string::npos) ? path : path.substr(slash + 1);
        if (name.size() >= 7 && (name[0] == 'N' || name[0] == 'S') &&
            std::isdigit(static_cast<unsigned char>(name[1]))) {
            latitude = std::stod(name.substr(1, 2));
            if (name[0] == 'S') latitude = -latitude;
        }
        const double dy = 30.87 * arcsec;
        const double dx = dy * std::cos(latitude * 3.14159265358979323846 / 180.0);
        dem.spacing_ = 0.5 * (dx + dy);
    }

    dem.recompute_bounds();
    return dem;
}

void Dem::recompute_bounds() {
    const auto [lo, hi] = std::minmax_element(z_.begin(), z_.end());
    min_z_ = *lo;
    max_z_ = *hi;
}

bool Dem::in_bounds(double x, double y) const {
    return x >= 0.0 && y >= 0.0 && x <= extent_x() && y <= extent_y();
}

double Dem::elevation(double x, double y) const {
    double gx = x / spacing_;
    double gy = y / spacing_;
    gx = std::min(std::max(gx, 0.0), static_cast<double>(w_ - 1));
    gy = std::min(std::max(gy, 0.0), static_cast<double>(h_ - 1));

    int i = static_cast<int>(gx);
    int j = static_cast<int>(gy);
    if (i >= w_ - 1) i = w_ - 2;
    if (j >= h_ - 1) j = h_ - 2;
    if (i < 0) i = 0;
    if (j < 0) j = 0;

    const double fx = gx - i;
    const double fy = gy - j;

    const double z00 = at(i,     j);
    const double z10 = at(i + 1, j);
    const double z01 = at(i,     j + 1);
    const double z11 = at(i + 1, j + 1);

    const double top = z00 + (z10 - z00) * fx;
    const double bot = z01 + (z11 - z01) * fx;
    return top + (bot - top) * fy;
}

Vec2 Dem::gradient(double x, double y) const {
    double gx = x / spacing_;
    double gy = y / spacing_;
    gx = std::min(std::max(gx, 0.0), static_cast<double>(w_ - 1));
    gy = std::min(std::max(gy, 0.0), static_cast<double>(h_ - 1));

    int i = static_cast<int>(gx);
    int j = static_cast<int>(gy);
    if (i >= w_ - 1) i = w_ - 2;
    if (j >= h_ - 1) j = h_ - 2;
    if (i < 0) i = 0;
    if (j < 0) j = 0;

    const double fx = gx - i;
    const double fy = gy - j;

    const double z00 = at(i,     j);
    const double z10 = at(i + 1, j);
    const double z01 = at(i,     j + 1);
    const double z11 = at(i + 1, j + 1);

    // d/dx and d/dy of z = z00(1-fx)(1-fy) + z10 fx(1-fy) + z01(1-fx)fy + z11 fx fy
    const double dz_dfx = (z10 - z00) * (1.0 - fy) + (z11 - z01) * fy;
    const double dz_dfy = (z01 - z00) * (1.0 - fx) + (z11 - z10) * fx;
    return Vec2{dz_dfx / spacing_, dz_dfy / spacing_};
}

double Dem::roughness(double x, double y, double window) const {
    const int half = std::max(1, static_cast<int>(window / spacing_ / 2.0));
    const int ci = std::min(std::max(static_cast<int>(x / spacing_), 0), w_ - 1);
    const int cj = std::min(std::max(static_cast<int>(y / spacing_), 0), h_ - 1);

    double sum = 0.0;
    double sum2 = 0.0;
    int n = 0;
    for (int j = std::max(0, cj - half); j <= std::min(h_ - 1, cj + half); ++j) {
        for (int i = std::max(0, ci - half); i <= std::min(w_ - 1, ci + half); ++i) {
            const double z = at(i, j);
            sum += z;
            sum2 += z * z;
            ++n;
        }
    }
    if (n < 2) return 0.0;
    const double mean = sum / n;
    return std::sqrt(std::max(0.0, sum2 / n - mean * mean));
}

double Dem::mean_slope() const {
    double sum = 0.0;
    long n = 0;
    for (int j = 1; j < h_ - 1; ++j) {
        for (int i = 1; i < w_ - 1; ++i) {
            const double dx = (at(i + 1, j) - at(i - 1, j)) / (2.0 * spacing_);
            const double dy = (at(i, j + 1) - at(i, j - 1)) / (2.0 * spacing_);
            sum += std::sqrt(dx * dx + dy * dy);
            ++n;
        }
    }
    return n > 0 ? sum / n : 0.0;
}

Dem Dem::downsample(int factor) const {
    if (factor < 1) throw std::invalid_argument("downsample factor must be >= 1");
    if (factor == 1) return *this;

    Dem out;
    out.w_ = (w_ - 1) / factor + 1;
    out.h_ = (h_ - 1) / factor + 1;
    out.spacing_ = spacing_ * factor;
    out.z_.resize(static_cast<std::size_t>(out.w_) * out.h_);

    // Average the source block centred on each output node, so the coarse grid
    // keeps the same physical extent and the same mean elevation.
    const int half = factor / 2;
    for (int j = 0; j < out.h_; ++j) {
        for (int i = 0; i < out.w_; ++i) {
            const int ci = i * factor;
            const int cj = j * factor;
            double sum = 0.0;
            int n = 0;
            for (int dj = -half; dj <= half; ++dj) {
                for (int di = -half; di <= half; ++di) {
                    const int si = std::min(std::max(ci + di, 0), w_ - 1);
                    const int sj = std::min(std::max(cj + dj, 0), h_ - 1);
                    sum += at(si, sj);
                    ++n;
                }
            }
            out.z_[static_cast<std::size_t>(j) * out.w_ + i] = static_cast<float>(sum / n);
        }
    }
    out.recompute_bounds();
    return out;
}
