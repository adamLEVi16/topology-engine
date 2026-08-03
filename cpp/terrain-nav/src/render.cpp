#include "render.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>

namespace {

constexpr double kPi = 3.14159265358979323846;

struct Rgb {
    std::uint8_t r = 0, g = 0, b = 0;
};
// The pixel buffer is written to disk in one block, which is only valid if the
// struct is exactly three tightly packed bytes.
static_assert(sizeof(Rgb) == 3, "Rgb must be tightly packed for the raw PPM write");

struct Canvas {
    int w = 0, h = 0;
    std::vector<Rgb> px;

    void set(int x, int y, Rgb c) {
        if (x < 0 || y < 0 || x >= w || y >= h) return;
        px[static_cast<std::size_t>(y) * w + x] = c;
    }
    void blend(int x, int y, Rgb c, double alpha) {
        if (x < 0 || y < 0 || x >= w || y >= h) return;
        Rgb& d = px[static_cast<std::size_t>(y) * w + x];
        d.r = static_cast<std::uint8_t>(d.r * (1 - alpha) + c.r * alpha);
        d.g = static_cast<std::uint8_t>(d.g * (1 - alpha) + c.g * alpha);
        d.b = static_cast<std::uint8_t>(d.b * (1 - alpha) + c.b * alpha);
    }
    void disc(int x, int y, int radius, Rgb c) {
        for (int dy = -radius; dy <= radius; ++dy)
            for (int dx = -radius; dx <= radius; ++dx)
                if (dx * dx + dy * dy <= radius * radius) set(x + dx, y + dy, c);
    }
};

// Elevation ramp: green lowlands through tan to bare rock and snow.
Rgb terrain_colour(double t) {
    static const double stops[5]      = {0.00, 0.30, 0.58, 0.80, 1.00};
    static const Rgb    colours[5]    = {{ 58, 92, 62}, { 96,120, 66}, {150,134, 88},
                                         {146,126,112}, {242,242,246}};
    t = std::min(std::max(t, 0.0), 1.0);
    for (int k = 0; k < 4; ++k) {
        if (t <= stops[k + 1]) {
            const double f = (t - stops[k]) / (stops[k + 1] - stops[k]);
            return Rgb{
                static_cast<std::uint8_t>(colours[k].r + f * (colours[k + 1].r - colours[k].r)),
                static_cast<std::uint8_t>(colours[k].g + f * (colours[k + 1].g - colours[k].g)),
                static_cast<std::uint8_t>(colours[k].b + f * (colours[k + 1].b - colours[k].b))};
        }
    }
    return colours[4];
}

void draw_line(Canvas& c, double x0, double y0, double x1, double y1, Rgb colour, int thickness) {
    const double dx = x1 - x0;
    const double dy = y1 - y0;
    const int steps = static_cast<int>(std::max(std::fabs(dx), std::fabs(dy))) + 1;
    for (int s = 0; s <= steps; ++s) {
        const double f = static_cast<double>(s) / steps;
        c.disc(static_cast<int>(std::lround(x0 + dx * f)),
               static_cast<int>(std::lround(y0 + dy * f)), thickness, colour);
    }
}

}  // namespace

void render_map(const Dem& dem,
                const std::vector<StepRecord>& history,
                const ParticleFilter& filter,
                const std::string& path,
                int max_pixels) {
    const int stride = std::max(1, (std::max(dem.width(), dem.height()) + max_pixels - 1) / max_pixels);

    Canvas canvas;
    canvas.w = dem.width() / stride;
    canvas.h = dem.height() / stride;
    if (canvas.w < 2 || canvas.h < 2) return;
    canvas.px.assign(static_cast<std::size_t>(canvas.w) * canvas.h, Rgb{});

    const double range = std::max(1.0, dem.max_elevation() - dem.min_elevation());

    // Hill shading with the light from the north-west at 45 degrees, which is
    // the cartographic convention — lit from the other side and the brain reads
    // ridges as valleys.
    const double azimuth = (360.0 - 315.0 + 90.0) * kPi / 180.0;
    const double zenith = (90.0 - 45.0) * kPi / 180.0;
    const double cell = dem.spacing() * stride;

    for (int py = 0; py < canvas.h; ++py) {
        for (int px = 0; px < canvas.w; ++px) {
            const int i = std::min(px * stride, dem.width() - 1);
            const int j = std::min((canvas.h - 1 - py) * stride, dem.height() - 1);

            const int im = std::max(i - stride, 0), ip = std::min(i + stride, dem.width() - 1);
            const int jm = std::max(j - stride, 0), jp = std::min(j + stride, dem.height() - 1);

            const double dzdx = (dem.at(ip, j) - dem.at(im, j)) / (2.0 * cell);
            const double dzdy = (dem.at(i, jp) - dem.at(i, jm)) / (2.0 * cell);

            const double slope = std::atan(std::sqrt(dzdx * dzdx + dzdy * dzdy));
            const double aspect = std::atan2(dzdy, -dzdx);
            double shade = std::cos(zenith) * std::cos(slope) +
                           std::sin(zenith) * std::sin(slope) * std::cos(azimuth - aspect);
            shade = std::min(std::max(shade, 0.0), 1.0);

            const Rgb base = terrain_colour((dem.at(i, j) - dem.min_elevation()) / range);
            const double lit = 0.35 + 0.65 * shade;
            canvas.set(px, py, Rgb{static_cast<std::uint8_t>(base.r * lit),
                                   static_cast<std::uint8_t>(base.g * lit),
                                   static_cast<std::uint8_t>(base.b * lit)});
        }
    }

    auto to_px = [&](double x) { return x / (dem.spacing() * stride); };
    auto to_py = [&](double y) { return (dem.extent_y() - y) / (dem.spacing() * stride); };

    // Final particle cloud first, so the tracks draw on top of it.
    const auto& particles = filter.particles();
    const auto& weights = filter.weights();
    double max_w = 0.0;
    for (double w : weights) max_w = std::max(max_w, w);
    for (std::size_t k = 0; k < particles.size(); ++k) {
        const double alpha = max_w > 0.0 ? std::min(1.0, 0.15 + 0.85 * weights[k] / max_w) : 0.2;
        canvas.blend(static_cast<int>(std::lround(to_px(particles[k].x))),
                     static_cast<int>(std::lround(to_py(particles[k].y))),
                     Rgb{255, 255, 255}, alpha);
    }

    for (std::size_t k = 1; k < history.size(); ++k) {
        const auto& a = history[k - 1];
        const auto& b = history[k];
        // Dead reckoning in red, terrain-aided in cyan, truth in black on top.
        draw_line(canvas, to_px(a.dr_x), to_py(a.dr_y), to_px(b.dr_x), to_py(b.dr_y),
                  Rgb{235, 60, 50}, 1);
        draw_line(canvas, to_px(a.pf_x), to_py(a.pf_y), to_px(b.pf_x), to_py(b.pf_y),
                  Rgb{60, 220, 235}, 1);
        draw_line(canvas, to_px(a.true_x), to_py(a.true_y), to_px(b.true_x), to_py(b.true_y),
                  Rgb{15, 15, 15}, 1);
    }

    if (!history.empty()) {
        canvas.disc(static_cast<int>(std::lround(to_px(history.front().true_x))),
                    static_cast<int>(std::lround(to_py(history.front().true_y))), 4,
                    Rgb{255, 235, 60});
    }

    std::ofstream out(path, std::ios::binary);
    if (!out) {
        std::cerr << "warning: cannot write " << path << "\n";
        return;
    }
    out << "P6\n" << canvas.w << ' ' << canvas.h << "\n255\n";
    out.write(reinterpret_cast<const char*>(canvas.px.data()),
              static_cast<std::streamsize>(canvas.px.size() * 3));
}
