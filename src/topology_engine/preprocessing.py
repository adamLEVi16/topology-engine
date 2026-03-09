from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler


@dataclass(slots=True)
class PreparedData:
    numeric: pd.DataFrame
    matrix: np.ndarray
    metadata: pd.DataFrame
    summary: dict[str, object]


def prepare_data(
    frame: pd.DataFrame,
    label_column: str | None = None,
    id_column: str | None = None,
    sample_size: int | None = None,
    random_seed: int = 42,
) -> PreparedData:
    if frame.empty:
        raise ValueError("Input dataset is empty.")

    metadata_columns = [col for col in [id_column, label_column] if col]
    missing = [col for col in metadata_columns if col not in frame.columns]
    if missing:
        raise ValueError(f"Missing metadata columns: {missing}")

    metadata = frame.loc[:, metadata_columns].copy() if metadata_columns else pd.DataFrame(index=frame.index)
    numeric = frame.drop(columns=metadata_columns, errors="ignore").select_dtypes(include=["number"]).copy()
    if numeric.shape[1] == 0:
        raise ValueError("No numeric feature columns found after excluding metadata.")

    numeric = numeric.loc[:, numeric.nunique(dropna=False) > 1]
    if numeric.shape[1] == 0:
        raise ValueError("All numeric columns were constant.")

    sampled = False
    if sample_size and len(numeric) > sample_size:
        rng = np.random.default_rng(random_seed)
        indices = np.sort(rng.choice(len(numeric), size=sample_size, replace=False))
        numeric = numeric.iloc[indices].reset_index(drop=True)
        metadata = metadata.iloc[indices].reset_index(drop=True) if not metadata.empty else metadata
        sampled = True
    else:
        numeric = numeric.reset_index(drop=True)
        metadata = metadata.reset_index(drop=True) if not metadata.empty else metadata

    imputer = SimpleImputer(strategy="median")
    scaler = StandardScaler()
    matrix = imputer.fit_transform(numeric)
    matrix = scaler.fit_transform(matrix)

    summary = {
        "original_rows": int(len(frame)),
        "rows_used": int(len(numeric)),
        "feature_columns": int(numeric.shape[1]),
        "sampled": sampled,
        "dropped_non_numeric": int(frame.shape[1] - len(metadata_columns) - numeric.shape[1]),
        "metadata_columns": metadata_columns,
        "imputation": "median",
        "scaling": "zscore",
    }
    return PreparedData(numeric=numeric, matrix=matrix, metadata=metadata, summary=summary)
