#include "neural_map.hpp"

#include <array>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <stdexcept>

namespace {

constexpr int kMaxWidth = 256;

template <typename T>
T read_pod(std::istream& in, const std::string& path) {
    T value{};
    if (!in.read(reinterpret_cast<char*>(&value), sizeof(T))) {
        throw std::runtime_error("unexpected end of " + path);
    }
    return value;
}

}  // namespace

NeuralMap NeuralMap::load(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw std::runtime_error("cannot open neural map: " + path);

    char magic[8] = {};
    if (!in.read(magic, 8) || std::string(magic, 7) != "SIREN01") {
        throw std::runtime_error(path + ": not a SIREN01 file");
    }

    NeuralMap map;
    map.extent_x_ = read_pod<float>(in, path);
    map.extent_y_ = read_pod<float>(in, path);
    map.x_scale_  = read_pod<float>(in, path);
    map.y_scale_  = read_pod<float>(in, path);
    map.z_scale_  = read_pod<float>(in, path);
    map.z_offset_ = read_pod<float>(in, path);

    // The file is a raw little-endian dump, so a big-endian reader would load
    // byte-swapped garbage and navigate against a scrambled network without ever
    // reporting an error. Byte-swapping a plausible extent or scale almost always
    // produces a denormal, a huge value, or a NaN, so validating the header
    // catches the mismatch at load time instead of silently at altitude.
    const bool header_sane =
        std::isfinite(map.extent_x_) && std::isfinite(map.extent_y_) &&
        std::isfinite(map.x_scale_)  && std::isfinite(map.y_scale_)  &&
        std::isfinite(map.z_scale_)  && std::isfinite(map.z_offset_) &&
        map.extent_x_ > 1.0 && map.extent_x_ < 1e9 &&
        map.extent_y_ > 1.0 && map.extent_y_ < 1e9 &&
        map.x_scale_  > 1e-6 && map.y_scale_ > 1e-6 && map.z_scale_ > 1e-6;
    if (!header_sane) {
        throw std::runtime_error(
            path + ": header values are implausible. The format is little-endian "
                   "float32; this usually means the file is byte-swapped, truncated, "
                   "or not a SIREN map at all.");
    }

    const auto n_layers = read_pod<std::int32_t>(in, path);
    if (n_layers < 1 || n_layers > 32) {
        throw std::runtime_error(path + ": implausible layer count");
    }

    int expected_in = 2;   // the network takes (x, y)
    for (int l = 0; l < n_layers; ++l) {
        Layer layer;
        layer.in    = read_pod<std::int32_t>(in, path);
        layer.out   = read_pod<std::int32_t>(in, path);
        layer.omega = read_pod<float>(in, path);

        if (layer.in < 1 || layer.out < 1 ||
            layer.in > kMaxWidth || layer.out > kMaxWidth) {
            throw std::runtime_error(path + ": layer wider than the " +
                                     std::to_string(kMaxWidth) + " unit limit");
        }

        // Layers must chain. Without this a file whose declared widths disagree
        // loads happily and evaluates against whatever stale values are left in
        // the activation buffer, returning confident nonsense. The finite
        // difference self-check cannot catch it either, since both paths
        // evaluate the same wrong network.
        if (layer.in != expected_in) {
            throw std::runtime_error(
                path + ": layer " + std::to_string(l) + " takes " +
                std::to_string(layer.in) + " inputs but the previous layer emits " +
                std::to_string(expected_in));
        }
        expected_in = layer.out;

        // omega is either exactly 0 (the linear output layer) or a frequency
        // scale. A denormal or absurd value collapses the network to a constant,
        // which reads downstream as terrain with no information rather than as a
        // corrupt file.
        if (!std::isfinite(layer.omega) ||
            (layer.omega != 0.0 && (layer.omega < 0.1 || layer.omega > 1000.0))) {
            throw std::runtime_error(
                path + ": layer " + std::to_string(l) + " has implausible omega " +
                std::to_string(layer.omega) + " (expected 0 or 0.1 to 1000)");
        }

        layer.weight.resize(static_cast<std::size_t>(layer.in) * layer.out);
        layer.bias.resize(static_cast<std::size_t>(layer.out));
        if (!in.read(reinterpret_cast<char*>(layer.weight.data()),
                     static_cast<std::streamsize>(layer.weight.size() * sizeof(float))) ||
            !in.read(reinterpret_cast<char*>(layer.bias.data()),
                     static_cast<std::streamsize>(layer.bias.size() * sizeof(float)))) {
            throw std::runtime_error("truncated layer data in " + path);
        }

        map.parameter_count_ += layer.weight.size() + layer.bias.size();
        map.layers_.push_back(std::move(layer));
    }

    if (map.layers_.front().in != 2 || map.layers_.back().out != 1) {
        throw std::runtime_error(path + ": expected a 2-input, 1-output network");
    }
    return map;
}

double NeuralMap::evaluate(double x, double y, Vec2* jacobian) const {
    // Activations, plus the derivative of each activation with respect to the
    // two inputs. Forward-mode is the right choice here: two inputs, one output,
    // so carrying the Jacobian forward costs 2x rather than a full backward pass.
    std::array<double, kMaxWidth> h{}, h_next{};
    std::array<double, kMaxWidth> dx{}, dy{}, dx_next{}, dy_next{};

    h[0] = x / x_scale_;
    h[1] = y / y_scale_;

    if (jacobian) {
        dx[0] = 1.0 / x_scale_; dx[1] = 0.0;
        dy[0] = 0.0;            dy[1] = 1.0 / y_scale_;
    }

    for (const Layer& layer : layers_) {
        for (int o = 0; o < layer.out; ++o) {
            const float* row = layer.weight.data() + static_cast<std::size_t>(o) * layer.in;

            double pre = layer.bias[o];
            double pre_dx = 0.0;
            double pre_dy = 0.0;
            for (int i = 0; i < layer.in; ++i) {
                pre += row[i] * h[i];
                if (jacobian) {
                    pre_dx += row[i] * dx[i];
                    pre_dy += row[i] * dy[i];
                }
            }

            if (layer.omega > 0.0) {
                // h = sin(omega * pre)  ->  dh = omega * cos(omega * pre) * dpre
                const double arg = layer.omega * pre;
                h_next[o] = std::sin(arg);
                if (jacobian) {
                    const double d = layer.omega * std::cos(arg);
                    dx_next[o] = d * pre_dx;
                    dy_next[o] = d * pre_dy;
                }
            } else {
                h_next[o] = pre;               // linear output layer
                if (jacobian) {
                    dx_next[o] = pre_dx;
                    dy_next[o] = pre_dy;
                }
            }
        }
        h = h_next;
        if (jacobian) {
            dx = dx_next;
            dy = dy_next;
        }
    }

    if (jacobian) {
        jacobian->x = dx[0] * z_scale_;
        jacobian->y = dy[0] * z_scale_;
    }
    return h[0] * z_scale_ + z_offset_;
}

double NeuralMap::elevation(double x, double y) const {
    return evaluate(x, y, nullptr);
}

Vec2 NeuralMap::gradient(double x, double y) const {
    Vec2 g;
    evaluate(x, y, &g);
    return g;
}

void NeuralMap::sample(double x, double y, double& elevation_out,
                       Vec2& gradient_out) const {
    elevation_out = evaluate(x, y, &gradient_out);
}

bool NeuralMap::in_bounds(double x, double y) const {
    return x >= 0.0 && y >= 0.0 && x <= extent_x_ && y <= extent_y_;
}

std::string NeuralMap::describe() const {
    std::string dims = std::to_string(layers_.front().in);
    for (const Layer& l : layers_) dims += "-" + std::to_string(l.out);
    return "SIREN " + dims + ", " + std::to_string(parameter_count_) + " params";
}
