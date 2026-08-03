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

    const auto n_layers = read_pod<std::int32_t>(in, path);
    if (n_layers < 1 || n_layers > 32) {
        throw std::runtime_error(path + ": implausible layer count");
    }

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
    int width = 2;

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
        width = layer.out;
        if (jacobian) {
            dx = dx_next;
            dy = dy_next;
        }
    }
    (void)width;

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

bool NeuralMap::in_bounds(double x, double y) const {
    return x >= 0.0 && y >= 0.0 && x <= extent_x_ && y <= extent_y_;
}

std::string NeuralMap::describe() const {
    std::string dims = std::to_string(layers_.front().in);
    for (const Layer& l : layers_) dims += "-" + std::to_string(l.out);
    return "SIREN " + dims + ", " + std::to_string(parameter_count_) + " params";
}
