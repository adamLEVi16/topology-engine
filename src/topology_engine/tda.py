from __future__ import annotations

import math

import numpy as np
from ripser import ripser


def compute_persistence(
    points: np.ndarray,
    max_dim: int = 1,
    metric: str = "euclidean",
    thresh: float | None = None,
) -> dict[str, object]:
    kwargs = {
        "maxdim": max_dim,
        "metric": metric,
    }
    if thresh is not None:
        kwargs["thresh"] = thresh
    result = ripser(points, **kwargs)
    diagrams = result["dgms"]
    return {"diagrams": diagrams, "result": result}


def persistence_summary(diagrams: list[np.ndarray]) -> dict[str, dict[str, float]]:
    summary: dict[str, dict[str, float]] = {}
    for dim, diagram in enumerate(diagrams):
        finite = _finite_pairs(diagram)
        pers = finite[:, 1] - finite[:, 0] if len(finite) else np.array([], dtype=float)
        summary[f"H{dim}"] = {
            "count": float(len(finite)),
            "max_persistence": float(pers.max()) if len(pers) else 0.0,
            "mean_persistence": float(pers.mean()) if len(pers) else 0.0,
            "total_persistence": float(pers.sum()) if len(pers) else 0.0,
        }
    return summary


def scalar_metrics(diagrams: list[np.ndarray]) -> dict[str, float]:
    h0 = _dimension_persistence(diagrams, 0)
    h1 = _dimension_persistence(diagrams, 1)
    all_parts = [p for p in (h0, h1) if len(p)]
    all_pers = np.concatenate(all_parts) if all_parts else np.array([], dtype=float)
    entropy = persistence_entropy(all_pers)
    complexity = 0.0
    complexity += 0.35 * float(h1.sum()) if len(h1) else 0.0
    complexity += 0.20 * float(h1.max()) if len(h1) else 0.0
    complexity += 0.20 * float(len(h1))
    complexity += 0.15 * entropy
    complexity += 0.10 * float(h0.sum()) if len(h0) else 0.0

    return {
        "H0_count": float(len(h0)),
        "H1_count": float(len(h1)),
        "max_persistence": float(all_pers.max()) if len(all_pers) else 0.0,
        "mean_persistence": float(all_pers.mean()) if len(all_pers) else 0.0,
        "total_persistence": float(all_pers.sum()) if len(all_pers) else 0.0,
        "persistence_entropy": float(entropy),
        "topological_complexity": float(complexity),
    }


def persistence_entropy(persistences: np.ndarray) -> float:
    if len(persistences) == 0:
        return 0.0
    total = float(np.sum(persistences))
    if total <= 0:
        return 0.0
    probs = persistences / total
    return float(-np.sum(probs * np.log(probs + 1e-12)))


def betti_curve(diagram: np.ndarray, resolution: int = 200) -> tuple[np.ndarray, np.ndarray]:
    finite = _finite_pairs(diagram)
    if len(finite) == 0:
        grid = np.linspace(0.0, 1.0, resolution)
        return grid, np.zeros_like(grid)
    xmin = float(np.min(finite[:, 0]))
    xmax = float(np.max(finite[:, 1]))
    if math.isclose(xmin, xmax):
        xmax = xmin + 1.0
    grid = np.linspace(xmin, xmax, resolution)
    counts = np.array([np.sum((finite[:, 0] <= x) & (finite[:, 1] > x)) for x in grid], dtype=float)
    return grid, counts


def barcode_segments(diagram: np.ndarray) -> list[tuple[float, float]]:
    finite = _finite_pairs(diagram)
    return [(float(b), float(d)) for b, d in finite]


def _finite_pairs(diagram: np.ndarray) -> np.ndarray:
    if diagram is None or len(diagram) == 0:
        return np.empty((0, 2), dtype=float)
    mask = np.isfinite(diagram).all(axis=1)
    return diagram[mask]


def _dimension_persistence(diagrams: list[np.ndarray], dim: int) -> np.ndarray:
    if dim >= len(diagrams):
        return np.array([], dtype=float)
    finite = _finite_pairs(diagrams[dim])
    if len(finite) == 0:
        return np.array([], dtype=float)
    return finite[:, 1] - finite[:, 0]
