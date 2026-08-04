#include "stl_export.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <ostream>
#include <stdexcept>
#include <utility>
#include <vector>

namespace {

struct V3 { float x = 0, y = 0, z = 0; };

// Binary STL: 80-byte header, uint32 count, then 50 bytes per triangle.
// Chosen over ASCII purely for size — a 300x300 heightmap is ~180k triangles,
// which is 9 MB binary and roughly 30 MB as text.
class StlWriter {
public:
    explicit StlWriter(const std::string& path) : out_(path, std::ios::binary) {
        if (!out_) throw std::runtime_error("cannot write " + path);
        const char header[80] = "terrain-nav heightmap";
        out_.write(header, 80);
        std::uint32_t placeholder = 0;
        out_.write(reinterpret_cast<const char*>(&placeholder), 4);
    }

    // Winding is the caller's responsibility and is never corrected here.
    // An earlier version flipped vertex order to make each normal point
    // outward, which produced correct-looking normals and a mesh that was not
    // closed: flipping reverses a triangle's edge directions, so its edges stop
    // pairing with its neighbours'. In a closed solid every directed edge must
    // appear exactly once and its reverse exactly once, and that is a property
    // of winding, not of normals.
    void triangle(V3 a, V3 b, V3 c) {
        const V3 n = cross(sub(b, a), sub(c, a));
        const float len = std::sqrt(dot(n, n));
        V3 unit = n;
        if (len > 0.0f) { unit.x = n.x / len; unit.y = n.y / len; unit.z = n.z / len; }
        write(unit); write(a); write(b); write(c);
        const std::uint16_t attr = 0;
        out_.write(reinterpret_cast<const char*>(&attr), 2);
        ++count_;
    }

    std::size_t finish() {
        out_.seekp(80);
        const auto n = static_cast<std::uint32_t>(count_);
        out_.write(reinterpret_cast<const char*>(&n), 4);
        return count_;
    }

private:
    static V3 sub(const V3& a, const V3& b) { return V3{a.x - b.x, a.y - b.y, a.z - b.z}; }
    static V3 cross(const V3& a, const V3& b) {
        return V3{a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x};
    }
    static float dot(const V3& a, const V3& b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
    void write(const V3& v) { out_.write(reinterpret_cast<const char*>(&v), 12); }

    std::ofstream out_;
    std::size_t count_ = 0;
};

}  // namespace

std::size_t write_stl(const Dem& dem, const std::string& path,
                      const StlOptions& options, std::ostream& log) {
    if (options.width_mm <= 0.0) throw std::invalid_argument("STL width must be > 0");
    if (options.max_samples < 2) throw std::invalid_argument("STL sample count must be >= 2");

    const int stride = std::max(1, (std::max(dem.width(), dem.height()) + options.max_samples - 1) /
                                       options.max_samples);
    const int nx = (dem.width()  - 1) / stride + 1;
    const int ny = (dem.height() - 1) / stride + 1;
    if (nx < 2 || ny < 2) throw std::invalid_argument("DEM too small to export");

    // Scale so the longer ground axis maps to width_mm, keeping the plan view
    // square-on-square rather than stretched.
    const double ground_long = std::max(dem.extent_x(), dem.extent_y());
    const double mm_per_metre = options.width_mm / ground_long;
    const double z_scale = mm_per_metre * options.exaggeration;
    const double min_z = dem.min_elevation();
    const double relief_mm = (dem.max_elevation() - min_z) * z_scale;

    auto vertex = [&](int i, int j) {
        const int si = std::min(i * stride, dem.width() - 1);
        const int sj = std::min(j * stride, dem.height() - 1);
        return V3{static_cast<float>(si * dem.spacing() * mm_per_metre),
                  static_cast<float>(sj * dem.spacing() * mm_per_metre),
                  static_cast<float>(options.base_mm + (dem.at(si, sj) - min_z) * z_scale)};
    };
    auto floor_at = [&](int i, int j) {
        V3 v = vertex(i, j);
        v.z = 0.0f;
        return v;
    };

    StlWriter stl(path);

    // Top surface, wound counter-clockwise seen from above so its normals face
    // +z. Its outer boundary therefore also runs counter-clockwise, which fixes
    // the winding every other face has to agree with.
    for (int j = 0; j + 1 < ny; ++j) {
        for (int i = 0; i + 1 < nx; ++i) {
            const V3 a = vertex(i, j), b = vertex(i + 1, j);
            const V3 c = vertex(i + 1, j + 1), d = vertex(i, j + 1);
            stl.triangle(a, b, c);
            stl.triangle(a, c, d);
        }
    }

    // The perimeter in that same counter-clockwise order. Every skirt and base
    // triangle is built from this list, so their edges subdivide identically to
    // the surface's and no T-junctions can appear.
    std::vector<std::pair<int, int>> ring;
    ring.reserve(2 * (nx + ny));
    for (int i = 0; i + 1 < nx; ++i)      ring.emplace_back(i, 0);
    for (int j = 0; j + 1 < ny; ++j)      ring.emplace_back(nx - 1, j);
    for (int i = nx - 1; i > 0; --i)      ring.emplace_back(i, ny - 1);
    for (int j = ny - 1; j > 0; --j)      ring.emplace_back(0, j);

    const std::size_t ring_n = ring.size();
    for (std::size_t k = 0; k < ring_n; ++k) {
        const auto [i0, j0] = ring[k];
        const auto [i1, j1] = ring[(k + 1) % ring_n];
        const V3 t0 = vertex(i0, j0),   t1 = vertex(i1, j1);
        const V3 b0 = floor_at(i0, j0), b1 = floor_at(i1, j1);
        // Top edge runs t1 -> t0, reversing the surface boundary edge t0 -> t1.
        stl.triangle(t1, t0, b0);
        stl.triangle(t1, b0, b1);
    }

    // Base as a fan over the same ring, wound clockwise from above for a -z
    // normal. Its boundary edges reverse the skirt's, closing the solid.
    for (std::size_t k = 1; k + 1 < ring_n; ++k) {
        const auto [i0, j0] = ring[0];
        const auto [ia, ja] = ring[k];
        const auto [ib, jb] = ring[k + 1];
        stl.triangle(floor_at(i0, j0), floor_at(ib, jb), floor_at(ia, ja));
    }

    const std::size_t triangles = stl.finish();

    log << std::fixed << std::setprecision(1)
        << "wrote " << path << "\n"
        << "  mesh        " << nx << " x " << ny << " samples, "
        << triangles << " triangles\n"
        << "  footprint   " << dem.extent_x() * mm_per_metre << " x "
        << dem.extent_y() * mm_per_metre << " mm\n"
        << "  relief      " << std::setprecision(2) << relief_mm << " mm"
        << " above a " << options.base_mm << " mm base"
        << " (exaggeration " << options.exaggeration << "x)\n"
        << "  scale       1 : " << std::setprecision(0) << 1000.0 / mm_per_metre << "\n";
    if (relief_mm < 2.0) {
        log << "  note: under 2 mm of relief will barely read as terrain. "
               "Raise --stl-exaggeration.\n";
    }
    return triangles;
}
