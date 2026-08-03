#!/usr/bin/env python3
"""Fit a SIREN to a terrain grid and export it for the C++ navigator.

A SIREN is an MLP with sinusoidal activations. Sine activations matter here
because their derivatives are also sinusoids, so the network stays smooth and
differentiable to all orders -- which is the whole point when the filter needs
analytic terrain gradients rather than differenced neighbours.

Pure NumPy with hand-written backprop: the network is small enough that a deep
learning framework would be more dependency than arithmetic.

Usage:
    python3 train_siren.py --input terrain.f32 --width 800 --height 800 \\
        --spacing 30 --hidden 64 --layers 3 --steps 4000 --out map.siren
"""

import argparse
import struct
import sys

import numpy as np


def build_network(hidden, layers, omega_first, omega_hidden, rng):
    """SIREN initialisation (Sitzmann et al. 2020).

    The first layer draws from U(-1/n, 1/n) and the rest from
    U(-sqrt(6/n)/omega, +...), which keeps every pre-activation roughly
    standard-normal regardless of depth. Getting this wrong is the usual reason
    a SIREN refuses to train at all.
    """
    dims = [2] + [hidden] * layers + [1]
    params = []
    for i in range(len(dims) - 1):
        fan_in, fan_out = dims[i], dims[i + 1]
        if i == 0:
            bound = 1.0 / fan_in
            omega = omega_first
        elif i == len(dims) - 2:
            bound = np.sqrt(6.0 / fan_in) / omega_hidden
            omega = 0.0            # linear output layer
        else:
            bound = np.sqrt(6.0 / fan_in) / omega_hidden
            omega = omega_hidden
        W = rng.uniform(-bound, bound, size=(fan_out, fan_in))
        b = np.zeros(fan_out)
        params.append({"W": W, "b": b, "omega": omega})
    return params


def forward(params, X, cache=None):
    """X is (N, 2). Returns (N,) predictions, optionally filling a cache."""
    h = X
    for idx, layer in enumerate(params):
        pre = h @ layer["W"].T + layer["b"]
        if cache is not None:
            cache.append({"input": h, "pre": pre})
        h = np.sin(layer["omega"] * pre) if layer["omega"] > 0 else pre
    return h[:, 0]


def backward(params, cache, grad_out):
    """grad_out is dL/d(output), shape (N,). Returns gradients per layer."""
    grads = [None] * len(params)
    g = grad_out[:, None]
    for idx in reversed(range(len(params))):
        layer = params[idx]
        entry = cache[idx]
        if layer["omega"] > 0:
            # d/dpre sin(omega * pre) = omega * cos(omega * pre)
            g = g * layer["omega"] * np.cos(layer["omega"] * entry["pre"])
        grads[idx] = {
            "W": g.T @ entry["input"] / len(g),
            "b": g.mean(axis=0),
        }
        g = g @ layer["W"]
    return grads


def train(params, X, Z, steps, batch, lr, rng, log_every=500):
    state = [{"mW": np.zeros_like(p["W"]), "vW": np.zeros_like(p["W"]),
              "mb": np.zeros_like(p["b"]), "vb": np.zeros_like(p["b"])} for p in params]
    b1, b2, eps = 0.9, 0.999, 1e-8

    for step in range(1, steps + 1):
        idx = rng.integers(0, len(X), size=batch)
        xb, zb = X[idx], Z[idx]

        cache = []
        pred = forward(params, xb, cache)
        residual = pred - zb
        loss = np.mean(residual ** 2)
        grads = backward(params, cache, 2.0 * residual)

        # Cosine decay: SIREN benefits from a long high-rate phase followed by a
        # genuinely small final rate, or the last percent of detail never lands.
        lr_t = lr * 0.5 * (1.0 + np.cos(np.pi * step / steps))

        for p, s, g in zip(params, state, grads):
            for key, mkey, vkey in (("W", "mW", "vW"), ("b", "mb", "vb")):
                s[mkey] = b1 * s[mkey] + (1 - b1) * g[key]
                s[vkey] = b2 * s[vkey] + (1 - b2) * g[key] ** 2
                m_hat = s[mkey] / (1 - b1 ** step)
                v_hat = s[vkey] / (1 - b2 ** step)
                p[key] -= lr_t * m_hat / (np.sqrt(v_hat) + eps)

        if step % log_every == 0 or step == 1:
            print(f"  step {step:6d}  loss {loss:.6f}  lr {lr_t:.2e}", flush=True)
    return params


def export(path, params, extent_x, extent_y, x_scale, y_scale, z_scale, z_offset):
    with open(path, "wb") as f:
        f.write(b"SIREN01\0")
        f.write(struct.pack("<6f", extent_x, extent_y, x_scale, y_scale, z_scale, z_offset))
        f.write(struct.pack("<i", len(params)))
        total = 0
        for layer in params:
            W, b = layer["W"], layer["b"]
            f.write(struct.pack("<iif", W.shape[1], W.shape[0], layer["omega"]))
            f.write(W.astype("<f4").tobytes())
            f.write(b.astype("<f4").tobytes())
            total += W.size + b.size
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="raw float32 elevation grid")
    ap.add_argument("--width", type=int, required=True)
    ap.add_argument("--height", type=int, required=True)
    ap.add_argument("--spacing", type=float, default=30.0)
    ap.add_argument("--hidden", type=int, default=64)
    ap.add_argument("--layers", type=int, default=3, help="hidden layers")
    ap.add_argument("--steps", type=int, default=4000)
    ap.add_argument("--batch", type=int, default=8192)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--omega-first", type=float, default=30.0)
    ap.add_argument("--omega-hidden", type=float, default=30.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    z = np.fromfile(args.input, dtype="<f4").astype(np.float64)
    if z.size != args.width * args.height:
        sys.exit(f"expected {args.width * args.height} samples, got {z.size}")
    z = z.reshape(args.height, args.width)

    ys, xs = np.meshgrid(np.arange(args.height), np.arange(args.width), indexing="ij")
    X_m = xs.ravel() * args.spacing
    Y_m = ys.ravel() * args.spacing

    extent_x = (args.width - 1) * args.spacing
    extent_y = (args.height - 1) * args.spacing

    # Normalise inputs to about [-1, 1] and standardise the output. Without this
    # the sine activations see arguments in the thousands and learn nothing.
    x_scale = extent_x / 2.0
    y_scale = extent_y / 2.0
    z_offset = float(z.mean())
    z_scale = float(z.std())

    X = np.stack([X_m / x_scale - 1.0, Y_m / y_scale - 1.0], axis=1)
    Z = (z.ravel() - z_offset) / z_scale

    rng = np.random.default_rng(args.seed)
    params = build_network(args.hidden, args.layers, args.omega_first, args.omega_hidden, rng)
    n_params = sum(p["W"].size + p["b"].size for p in params)
    print(f"SIREN 2-{'-'.join([str(args.hidden)] * args.layers)}-1  "
          f"{n_params} params  ({n_params * 4 / 1024:.1f} KiB)")
    print(f"grid {args.width}x{args.height} @ {args.spacing} m, "
          f"relief {z.max() - z.min():.0f} m")

    train(params, X, Z, args.steps, args.batch, args.lr, rng)

    pred = np.concatenate([forward(params, X[i:i + 65536]) for i in range(0, len(X), 65536)])
    rmse = float(np.sqrt(np.mean(((pred - Z) * z_scale) ** 2)))
    print(f"reconstruction RMSE {rmse:.2f} m over {z.max() - z.min():.0f} m of relief")

    # The C++ side normalises as x/x_scale, so fold the -1.0 shift into the
    # first layer's bias rather than carrying a separate offset.
    W0 = params[0]["W"]
    params[0]["b"] = params[0]["b"] - W0 @ np.array([1.0, 1.0])

    total = export(args.out, params, extent_x, extent_y, x_scale, y_scale, z_scale, z_offset)
    print(f"wrote {args.out}  ({total} params, {total * 4 / 1024:.1f} KiB)")


if __name__ == "__main__":
    main()
