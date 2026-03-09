from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass
class AnalysisResult:
    dataset_shape: tuple[int, int]
    preprocessing_summary: dict[str, Any]
    embedding_summary: dict[str, Any]
    persistence_summary: dict[str, Any]
    metrics: dict[str, float]
    null_summary: dict[str, dict[str, float]]
    significance: dict[str, dict[str, float]]
    null_replicates: dict[str, list[float]] = field(default_factory=dict)
    group_metrics: pd.DataFrame | None = None
    group_significance: pd.DataFrame | None = None
    artifact_paths: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "dataset_shape": list(self.dataset_shape),
            "preprocessing_summary": self.preprocessing_summary,
            "embedding_summary": self.embedding_summary,
            "persistence_summary": self.persistence_summary,
            "metrics": self.metrics,
            "null_summary": self.null_summary,
            "significance": self.significance,
            "null_replicates": self.null_replicates,
            "artifact_paths": self.artifact_paths,
        }
        if self.group_metrics is not None:
            payload["group_metrics"] = self.group_metrics.to_dict(orient="records")
        if self.group_significance is not None:
            payload["group_significance"] = self.group_significance.to_dict(orient="records")
        return payload

    def register_path(self, key: str, path: Path) -> None:
        self.artifact_paths[key] = str(path)
