from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class AnalysisConfig:
    embedding: str = "pca"
    metric: str = "euclidean"
    max_dim: int = 1
    sample_size: int | None = 2000
    pca_components: int = 15
    random_seed: int = 42
    n_null: int = 32
    null_model: str = "feature-permute"
    label_column: str | None = None
    id_column: str | None = None
    output_dir: Path | None = None
    report_format: str = "both"
    create_json: bool = False
    figure_dpi: int = 140
    persistence_threshold: float | None = None
    save_figures: bool = True
    generate_pdf: bool = True
    grouped_max_groups: int = 8
    min_group_size: int = 8
    report_title: str = "Topological Analysis Report"
    extra_metadata: dict[str, str] = field(default_factory=dict)
