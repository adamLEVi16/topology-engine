from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages
from persim import plot_diagrams

from topology_engine.results import AnalysisResult
from topology_engine.tda import barcode_segments, betti_curve


def prepare_output_dirs(output_dir: Path) -> dict[str, Path]:
    figures = output_dir / "figures"
    tables = output_dir / "tables"
    report = output_dir / "report"
    for path in [output_dir, figures, tables, report]:
        path.mkdir(parents=True, exist_ok=True)
    return {"root": output_dir, "figures": figures, "tables": tables, "report": report}


def write_tables(result: AnalysisResult, directories: dict[str, Path]) -> None:
    metrics_path = directories["tables"] / "metrics.csv"
    pd.DataFrame([result.metrics]).to_csv(metrics_path, index=False)
    result.register_path("metrics_csv", metrics_path)

    significance_path = directories["tables"] / "significance.csv"
    pd.DataFrame(
        [
            {
                "metric": metric,
                **summary,
                **result.significance[metric],
            }
            for metric, summary in result.null_summary.items()
        ]
    ).to_csv(significance_path, index=False)
    result.register_path("significance_csv", significance_path)

    if result.group_metrics is not None:
        group_metrics_path = directories["tables"] / "group_metrics.csv"
        result.group_metrics.to_csv(group_metrics_path, index=False)
        result.register_path("group_metrics_csv", group_metrics_path)

    if result.group_significance is not None:
        group_significance_path = directories["tables"] / "group_significance.csv"
        result.group_significance.to_csv(group_significance_path, index=False)
        result.register_path("group_significance_csv", group_significance_path)


def write_json(result: AnalysisResult, directories: dict[str, Path]) -> None:
    summary_path = directories["root"] / "summary.json"
    with summary_path.open("w", encoding="utf-8") as handle:
        json.dump(result.to_dict(), handle, indent=2)
    result.register_path("summary_json", summary_path)


def generate_figure_portfolio(
    result: AnalysisResult,
    diagrams: list[np.ndarray],
    embedding: np.ndarray,
    labels: pd.Series | None,
    directories: dict[str, Path],
    dpi: int = 140,
) -> list[Path]:
    output_paths = []
    output_paths.append(_embedding_plot(embedding, labels, directories["figures"] / "embedding_overview.png", dpi))
    output_paths.append(_persistence_plot(diagrams, directories["figures"] / "persistence_diagram.png", dpi))
    output_paths.append(_betti_plot(diagrams, directories["figures"] / "betti_curves.png", dpi))
    output_paths.append(_barcode_plot(diagrams, directories["figures"] / "barcode_summary.png", dpi))
    output_paths.append(
        _significance_plot(
            result.metrics,
            result.null_summary,
            result.significance,
            directories["figures"] / "metric_significance.png",
            dpi,
        )
    )
    output_paths.append(
        _null_distribution_plot(
            result,
            "topological_complexity",
            directories["figures"] / "null_distribution_topological_complexity.png",
            dpi,
        )
    )
    output_paths.append(_complexity_dashboard(result, directories["figures"] / "complexity_dashboard.png", dpi))
    if result.group_metrics is not None and not result.group_metrics.empty:
        output_paths.append(_group_plot(result.group_metrics, directories["figures"] / "group_comparison.png", dpi))
    return output_paths


def build_pdf_report(
    result: AnalysisResult,
    figure_paths: list[Path],
    directories: dict[str, Path],
    title: str,
) -> Path:
    pdf_path = directories["report"] / "topology_report.pdf"
    with PdfPages(pdf_path) as pdf:
        cover, cover_ax = plt.subplots(figsize=(8.27, 11.69))
        cover_ax.text(0.08, 0.95, title, fontsize=20, weight="bold", transform=cover_ax.transAxes)
        cover_ax.text(0.08, 0.90, f"Dataset shape: {result.dataset_shape[0]} rows x {result.dataset_shape[1]} columns", fontsize=11, transform=cover_ax.transAxes)
        cover_ax.text(0.08, 0.84, "Preprocessing", fontsize=14, weight="bold", transform=cover_ax.transAxes)
        y = 0.81
        for key, value in result.preprocessing_summary.items():
            cover_ax.text(0.10, y, f"{key}: {value}", fontsize=10, transform=cover_ax.transAxes)
            y -= 0.025
        cover_ax.text(0.08, y - 0.02, "Embedding", fontsize=14, weight="bold", transform=cover_ax.transAxes)
        y -= 0.05
        for key, value in result.embedding_summary.items():
            cover_ax.text(0.10, y, f"{key}: {value}", fontsize=10, transform=cover_ax.transAxes)
            y -= 0.025
        cover_ax.text(0.08, y - 0.02, "Key metrics", fontsize=14, weight="bold", transform=cover_ax.transAxes)
        y -= 0.05
        for key, value in result.metrics.items():
            cover_ax.text(0.10, y, f"{key}: {value:.4f}", fontsize=10, transform=cover_ax.transAxes)
            y -= 0.025
        cover_ax.axis("off")
        pdf.savefig(cover)
        plt.close(cover)

        for figure_path in figure_paths:
            image = plt.imread(figure_path)
            fig, ax = plt.subplots(figsize=(8.27, 11.69))
            ax.imshow(image)
            ax.axis("off")
            ax.set_title(figure_path.stem.replace("_", " ").title(), fontsize=14)
            pdf.savefig(fig, bbox_inches="tight")
            plt.close(fig)

        notes, notes_ax = plt.subplots(figsize=(8.27, 11.69))
        notes_ax.text(0.08, 0.95, "Interpretation Notes", fontsize=18, weight="bold", transform=notes_ax.transAxes)
        notes_ax.text(0.08, 0.88, "The null-distribution panel shows the empirical reference distribution from permutations.", fontsize=11, transform=notes_ax.transAxes)
        notes_ax.text(0.08, 0.84, "The vertical line is the observed statistic and the shaded tail marks the empirical p-value region.", fontsize=11, transform=notes_ax.transAxes)
        notes_ax.text(0.08, 0.80, "Topological complexity is a heuristic composite score for exploratory comparison.", fontsize=11, transform=notes_ax.transAxes)
        notes_ax.axis("off")
        pdf.savefig(notes)
        plt.close(notes)
    result.register_path("pdf_report", pdf_path)
    return pdf_path


def _embedding_plot(embedding: np.ndarray, labels: pd.Series | None, path: Path, dpi: int) -> Path:
    fig, ax = plt.subplots(figsize=(7, 5))
    if embedding.shape[1] == 1:
        xs = embedding[:, 0]
        ys = np.zeros(len(xs))
    else:
        xs = embedding[:, 0]
        ys = embedding[:, 1]
    if labels is not None and len(labels) == len(xs):
        categories = labels.astype(str)
        for name in categories.unique():
            mask = categories == name
            ax.scatter(xs[mask], ys[mask], s=18, alpha=0.75, label=name)
        ax.legend(frameon=False)
    else:
        ax.scatter(xs, ys, s=18, alpha=0.75)
    ax.set_title("Embedding Overview")
    ax.set_xlabel("Component 1")
    ax.set_ylabel("Component 2")
    fig.tight_layout()
    fig.savefig(path, dpi=dpi)
    plt.close(fig)
    return path


def _persistence_plot(diagrams: list[np.ndarray], path: Path, dpi: int) -> Path:
    fig, ax = plt.subplots(figsize=(6, 6))
    plot_diagrams(diagrams, ax=ax, show=False)
    ax.set_title("Persistence Diagram")
    fig.tight_layout()
    fig.savefig(path, dpi=dpi)
    plt.close(fig)
    return path


def _betti_plot(diagrams: list[np.ndarray], path: Path, dpi: int) -> Path:
    fig, ax = plt.subplots(figsize=(7, 5))
    for dim in range(min(2, len(diagrams))):
        grid, counts = betti_curve(diagrams[dim])
        ax.plot(grid, counts, label=f"H{dim}")
    ax.set_title("Betti Curves")
    ax.set_xlabel("Filtration")
    ax.set_ylabel("Count")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=dpi)
    plt.close(fig)
    return path


def _barcode_plot(diagrams: list[np.ndarray], path: Path, dpi: int) -> Path:
    rows = max(1, min(2, len(diagrams)))
    fig, axes = plt.subplots(nrows=rows, figsize=(7, 4 + 1.5 * rows))
    if not isinstance(axes, np.ndarray):
        axes = np.array([axes])
    for dim, ax in enumerate(axes):
        segments = barcode_segments(diagrams[dim])
        for idx, (birth, death) in enumerate(segments):
            ax.plot([birth, death], [idx, idx], color=f"C{dim}", linewidth=1.8)
        ax.set_title(f"H{dim} Barcode")
        ax.set_xlabel("Filtration")
        ax.set_ylabel("Feature")
    fig.tight_layout()
    fig.savefig(path, dpi=dpi)
    plt.close(fig)
    return path


def _significance_plot(
    metrics: dict[str, float],
    null_summary: dict[str, dict[str, float]],
    significance: dict[str, dict[str, float]],
    path: Path,
    dpi: int,
) -> Path:
    names = list(metrics.keys())
    observed = [metrics[name] for name in names]
    lowers = [null_summary[name]["lower_95"] for name in names]
    uppers = [null_summary[name]["upper_95"] for name in names]
    z_scores = [significance[name]["z_score"] for name in names]
    positions = np.arange(len(names))

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.fill_between(positions, lowers, uppers, color="#cfe8ff", alpha=0.8, label="Null 95% interval")
    ax.plot(positions, observed, "o-", color="#0b5394", linewidth=2, label="Observed")
    for idx, value in enumerate(observed):
        ax.text(idx, value, f"z={z_scores[idx]:.2f}", fontsize=8, ha="center", va="bottom")
    ax.set_xticks(positions)
    ax.set_xticklabels(names, rotation=35, ha="right")
    ax.set_title("Metric Significance vs Null")
    ax.set_ylabel("Value")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=dpi)
    plt.close(fig)
    return path


def _null_distribution_plot(result: AnalysisResult, metric_name: str, path: Path, dpi: int) -> Path:
    values = np.array(result.null_replicates.get(metric_name, []), dtype=float)
    observed = result.metrics[metric_name]
    p_value = result.significance[metric_name]["empirical_p"]
    z_score = result.significance[metric_name]["z_score"]

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(values, bins=min(20, max(8, len(values) // 8)), color="#cfe2f3", edgecolor="#6c8ebf", alpha=0.9)
    ax.axvline(observed, color="#cc0000", linewidth=2, label="Observed")
    if len(values):
        mean = values.mean()
        if observed >= mean:
            tail = values[values >= observed]
        else:
            tail = values[values <= observed]
        if len(tail):
            ax.hist(tail, bins=min(10, max(3, len(tail))), color="#f4cccc", edgecolor="#990000", alpha=0.95)
    ax.set_title(f"Null Distribution: {metric_name}")
    ax.set_xlabel("Metric value")
    ax.set_ylabel("Count")
    ax.text(0.98, 0.95, f"z = {z_score:.2f}\np = {p_value:.4f}", transform=ax.transAxes, ha="right", va="top", fontsize=10,
            bbox={"facecolor": "white", "edgecolor": "#999999", "alpha": 0.9})
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=dpi)
    plt.close(fig)
    return path


def _complexity_dashboard(result: AnalysisResult, path: Path, dpi: int) -> Path:
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.5))
    key_metrics = ["H0_count", "H1_count", "topological_complexity"]
    axes[0].bar(key_metrics, [result.metrics[name] for name in key_metrics], color=["#6fa8dc", "#3d85c6", "#073763"])
    axes[0].set_title("Core Topology Metrics")
    axes[0].tick_params(axis="x", rotation=25)

    z_names = ["max_persistence", "total_persistence", "persistence_entropy", "topological_complexity"]
    axes[1].bar(z_names, [result.significance[name]["z_score"] for name in z_names], color="#93c47d")
    axes[1].axhspan(-1.96, 1.96, color="#f4cccc", alpha=0.5)
    axes[1].set_title("Z-Score Dashboard")
    axes[1].tick_params(axis="x", rotation=25)
    axes[1].set_ylabel("z-score")
    fig.tight_layout()
    fig.savefig(path, dpi=dpi)
    plt.close(fig)
    return path


def _group_plot(group_metrics: pd.DataFrame, path: Path, dpi: int) -> Path:
    fig, ax = plt.subplots(figsize=(8, 5))
    pivot = group_metrics[["group", "topological_complexity", "H1_count", "max_persistence"]].set_index("group")
    pivot.plot(kind="bar", ax=ax)
    ax.set_title("Grouped Topology Comparison")
    ax.set_ylabel("Metric value")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=dpi)
    plt.close(fig)
    return path
