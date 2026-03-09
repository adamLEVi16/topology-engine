from __future__ import annotations

import numpy as np


def generate_null_samples(
    matrix: np.ndarray,
    n_null: int,
    null_model: str,
    random_seed: int = 42,
) -> list[np.ndarray]:
    rng = np.random.default_rng(random_seed)
    samples: list[np.ndarray] = []
    for _ in range(n_null):
        if null_model == "feature-permute":
            permuted = np.empty_like(matrix)
            for col in range(matrix.shape[1]):
                permuted[:, col] = rng.permutation(matrix[:, col])
            samples.append(permuted)
        elif null_model == "row-bootstrap":
            indices = rng.choice(matrix.shape[0], size=matrix.shape[0], replace=True)
            samples.append(matrix[indices])
        elif null_model == "distance-shuffle":
            indices = rng.permutation(matrix.shape[0])
            samples.append(matrix[indices])
        else:
            raise ValueError(f"Unsupported null model: {null_model}")
    return samples


def summarize_null_distribution(observed: dict[str, float], replicates: list[dict[str, float]]) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    names = observed.keys()
    summary: dict[str, dict[str, float]] = {}
    significance: dict[str, dict[str, float]] = {}
    for name in names:
        values = np.array([rep[name] for rep in replicates], dtype=float)
        obs = float(observed[name])
        mean = float(values.mean()) if len(values) else 0.0
        std = float(values.std(ddof=0)) if len(values) else 0.0
        lower = float(np.quantile(values, 0.025)) if len(values) else 0.0
        upper = float(np.quantile(values, 0.975)) if len(values) else 0.0
        z = float((obs - mean) / std) if std > 0 else 0.0
        centered = np.abs(values - mean) if len(values) else np.array([], dtype=float)
        p = float((np.sum(centered >= abs(obs - mean)) + 1) / (len(values) + 1)) if len(values) else 1.0
        summary[name] = {
            "mean": mean,
            "std": std,
            "lower_95": lower,
            "upper_95": upper,
        }
        significance[name] = {
            "observed": obs,
            "z_score": z,
            "empirical_p": p,
        }
    return summary, significance


def group_difference_significance(
    values: np.ndarray,
    labels: np.ndarray,
    metric_names: list[str],
    n_null: int,
    random_seed: int = 42,
) -> list[dict[str, float | str]]:
    unique = np.unique(labels)
    if len(unique) != 2:
        return []
    rng = np.random.default_rng(random_seed)
    a_mask = labels == unique[0]
    b_mask = labels == unique[1]
    observed = values[a_mask].mean(axis=0) - values[b_mask].mean(axis=0)
    outputs: list[dict[str, float | str]] = []
    for idx, metric in enumerate(metric_names):
        null_diffs = []
        for _ in range(n_null):
            shuffled = rng.permutation(labels)
            sa = shuffled == unique[0]
            sb = shuffled == unique[1]
            null_diffs.append(float(values[sa, idx].mean() - values[sb, idx].mean()))
        arr = np.array(null_diffs, dtype=float)
        std = float(arr.std(ddof=0))
        z = float((observed[idx] - arr.mean()) / std) if std > 0 else 0.0
        p = float((np.sum(np.abs(arr) >= abs(observed[idx])) + 1) / (len(arr) + 1))
        outputs.append(
            {
                "metric": metric,
                "group_a": str(unique[0]),
                "group_b": str(unique[1]),
                "observed_difference": float(observed[idx]),
                "z_score": z,
                "empirical_p": p,
            }
        )
    return outputs
