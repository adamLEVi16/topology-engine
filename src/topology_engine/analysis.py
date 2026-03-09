from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from topology_engine.config import AnalysisConfig
from topology_engine.embedding import compute_embedding
from topology_engine.null_models import generate_null_samples, summarize_null_distribution
from topology_engine.preprocessing import prepare_data
from topology_engine.reporting import (
    build_pdf_report,
    generate_figure_portfolio,
    prepare_output_dirs,
    write_json,
    write_tables,
)
from topology_engine.results import AnalysisResult
from topology_engine.tda import compute_persistence, persistence_summary, scalar_metrics


EMPTY_METRICS = {
    "H0_count": 0.0,
    "H1_count": 0.0,
    "max_persistence": 0.0,
    "mean_persistence": 0.0,
    "total_persistence": 0.0,
    "persistence_entropy": 0.0,
    "topological_complexity": 0.0,
}


def analyze_dataset(data: pd.DataFrame | np.ndarray, config: AnalysisConfig) -> AnalysisResult:
    frame = _ensure_frame(data)
    prepared = prepare_data(
        frame,
        label_column=config.label_column,
        id_column=config.id_column,
        sample_size=config.sample_size,
        random_seed=config.random_seed,
    )
    embedded, embedding_summary = compute_embedding(
        prepared.matrix,
        method=config.embedding,
        n_components=config.pca_components,
        random_seed=config.random_seed,
    )
    persistence = compute_persistence(
        embedded,
        max_dim=config.max_dim,
        metric=config.metric,
        thresh=config.persistence_threshold,
    )
    diagrams = persistence["diagrams"]
    persistence_stats = persistence_summary(diagrams)
    metrics = scalar_metrics(diagrams)

    null_samples = generate_null_samples(
        embedded,
        n_null=config.n_null,
        null_model=config.null_model,
        random_seed=config.random_seed,
    )
    null_metrics = [
        scalar_metrics(
            compute_persistence(
                sample,
                max_dim=config.max_dim,
                metric=config.metric,
                thresh=config.persistence_threshold,
            )["diagrams"]
        )
        for sample in null_samples
    ]
    null_summary, significance = summarize_null_distribution(metrics, null_metrics)
    null_replicates = {
        metric: [float(row[metric]) for row in null_metrics]
        for metric in metrics.keys()
    }

    group_metrics, group_significance = _compute_group_outputs(
        prepared.metadata,
        prepared.matrix,
        config,
    )

    result = AnalysisResult(
        dataset_shape=prepared.matrix.shape,
        preprocessing_summary=prepared.summary,
        embedding_summary=embedding_summary,
        persistence_summary=persistence_stats,
        metrics=metrics,
        null_summary=null_summary,
        significance=significance,
        null_replicates=null_replicates,
        group_metrics=group_metrics,
        group_significance=group_significance,
    )

    if config.output_dir is not None:
        directories = prepare_output_dirs(Path(config.output_dir))
        labels = prepared.metadata[config.label_column] if config.label_column and config.label_column in prepared.metadata else None
        figure_paths = generate_figure_portfolio(
            result=result,
            diagrams=diagrams,
            embedding=embedded,
            labels=labels,
            directories=directories,
            dpi=config.figure_dpi,
        )
        for idx, figure_path in enumerate(figure_paths, start=1):
            result.register_path(f"figure_{idx}", figure_path)
        write_tables(result, directories)
        write_json(result, directories)
        if config.report_format in {"pdf", "both"} and config.generate_pdf:
            build_pdf_report(result, figure_paths, directories, config.report_title)

    return result


def _compute_group_outputs(
    metadata: pd.DataFrame,
    matrix: np.ndarray,
    config: AnalysisConfig,
) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    if not config.label_column or config.label_column not in metadata:
        return None, None

    labels = metadata[config.label_column].astype(str)
    counts = labels.value_counts()
    eligible = counts[counts >= config.min_group_size].index.tolist()[: config.grouped_max_groups]
    if len(eligible) < 2:
        return None, None

    rows = []
    for group in eligible:
        subset = matrix[labels == group]
        rows.append({"group": group, **_metrics_for_matrix(subset, config)})
    group_df = pd.DataFrame(rows)

    significance_df = None
    if len(eligible) == 2:
        significance_df = _label_permutation_significance(matrix, labels, eligible, config)
    return group_df, significance_df


def _label_permutation_significance(
    matrix: np.ndarray,
    labels: pd.Series,
    eligible: list[str],
    config: AnalysisConfig,
) -> pd.DataFrame:
    metric_names = list(EMPTY_METRICS.keys())
    observed_metrics = []
    label_mask = labels.isin(eligible)
    relevant_matrix = matrix[label_mask.to_numpy()]
    relevant_labels = labels[label_mask].reset_index(drop=True)

    for group in eligible:
        observed_metrics.append(_metrics_for_matrix(relevant_matrix[relevant_labels == group], config))
    observed_diff = {
        metric: observed_metrics[0][metric] - observed_metrics[1][metric]
        for metric in metric_names
    }

    rng = np.random.default_rng(config.random_seed)
    null_rows = []
    labels_array = relevant_labels.to_numpy()
    for _ in range(config.n_null):
        shuffled = rng.permutation(labels_array)
        group_a = _metrics_for_matrix(relevant_matrix[shuffled == eligible[0]], config)
        group_b = _metrics_for_matrix(relevant_matrix[shuffled == eligible[1]], config)
        null_rows.append({metric: group_a[metric] - group_b[metric] for metric in metric_names})

    out_rows = []
    for metric in metric_names:
        null_values = np.array([row[metric] for row in null_rows], dtype=float)
        std = float(null_values.std(ddof=0))
        z = float((observed_diff[metric] - null_values.mean()) / std) if std > 0 else 0.0
        p = float((np.sum(np.abs(null_values) >= abs(observed_diff[metric])) + 1) / (len(null_values) + 1))
        out_rows.append(
            {
                "metric": metric,
                "group_a": eligible[0],
                "group_b": eligible[1],
                "observed_difference": float(observed_diff[metric]),
                "z_score": z,
                "empirical_p": p,
            }
        )
    return pd.DataFrame(out_rows)


def _metrics_for_matrix(matrix: np.ndarray, config: AnalysisConfig) -> dict[str, float]:
    if matrix.shape[0] < 3:
        return EMPTY_METRICS.copy()
    embedded, _ = compute_embedding(
        matrix,
        method=config.embedding,
        n_components=config.pca_components,
        random_seed=config.random_seed,
    )
    diagrams = compute_persistence(
        embedded,
        max_dim=config.max_dim,
        metric=config.metric,
        thresh=config.persistence_threshold,
    )["diagrams"]
    return scalar_metrics(diagrams)


def _ensure_frame(data: pd.DataFrame | np.ndarray) -> pd.DataFrame:
    if isinstance(data, pd.DataFrame):
        return data.copy()
    if isinstance(data, np.ndarray):
        return pd.DataFrame(data, columns=[f"feature_{i}" for i in range(data.shape[1])])
    raise TypeError("Data must be a pandas DataFrame or a 2D NumPy array.")
