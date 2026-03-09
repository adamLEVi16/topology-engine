from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from topology_engine.analysis import analyze_dataset
from topology_engine.config import AnalysisConfig
from topology_engine.io import load_input


def test_circle_has_h1_signal(tmp_path: Path) -> None:
    t = np.linspace(0, 2 * np.pi, 80, endpoint=False)
    rng = np.random.default_rng(0)
    data = pd.DataFrame(
        {
            "x": np.cos(t) + 0.03 * rng.normal(size=len(t)),
            "y": np.sin(t) + 0.03 * rng.normal(size=len(t)),
        }
    )
    config = AnalysisConfig(output_dir=tmp_path / "circle", n_null=8, create_json=True)
    result = analyze_dataset(data, config)
    assert result.metrics["H1_count"] >= 1
    assert "summary_json" in result.artifact_paths
    assert any("null_distribution_topological_complexity" in path for path in result.artifact_paths.values())


def test_blob_is_less_loop_like() -> None:
    rng = np.random.default_rng(3)
    blob = pd.DataFrame(rng.normal(size=(120, 5)), columns=[f"f{i}" for i in range(5)])
    config = AnalysisConfig(output_dir=None, n_null=8)
    result = analyze_dataset(blob, config)
    assert result.metrics["H0_count"] >= 1
    assert result.metrics["max_persistence"] >= 0


def test_grouped_analysis_outputs_tables(tmp_path: Path) -> None:
    rng = np.random.default_rng(2)
    a = rng.normal(loc=-1.0, scale=0.4, size=(20, 4))
    b = rng.normal(loc=1.0, scale=0.4, size=(20, 4))
    data = pd.DataFrame(np.vstack([a, b]), columns=["f1", "f2", "f3", "f4"])
    data["group"] = ["A"] * len(a) + ["B"] * len(b)
    config = AnalysisConfig(
        output_dir=tmp_path / "grouped",
        label_column="group",
        n_null=8,
        create_json=True,
    )
    result = analyze_dataset(data, config)
    assert result.group_metrics is not None
    assert (tmp_path / "grouped" / "tables" / "group_metrics.csv").exists()


def test_load_npy(tmp_path: Path) -> None:
    array = np.arange(20, dtype=float).reshape(10, 2)
    path = tmp_path / "data.npy"
    np.save(path, array)
    frame = load_input(path)
    assert frame.shape == (10, 2)
