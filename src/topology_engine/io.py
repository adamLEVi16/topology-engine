from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


SUPPORTED_SUFFIXES = {".csv", ".tsv", ".parquet", ".npy", ".npz"}


def load_input(path: str | Path, input_format: str = "auto") -> pd.DataFrame:
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    fmt = suffix if input_format == "auto" else _normalize_format(input_format)
    if fmt not in SUPPORTED_SUFFIXES:
        raise ValueError(f"Unsupported input format: {fmt}")

    if fmt == ".csv":
        return pd.read_csv(file_path)
    if fmt == ".tsv":
        return pd.read_csv(file_path, sep="\t")
    if fmt == ".parquet":
        return pd.read_parquet(file_path)
    if fmt == ".npy":
        array = np.load(file_path, allow_pickle=False)
        return _array_to_frame(array)
    if fmt == ".npz":
        archive = np.load(file_path, allow_pickle=False)
        if not archive.files:
            raise ValueError("NPZ archive did not contain any arrays.")
        return _array_to_frame(archive[archive.files[0]])
    raise ValueError(f"Unsupported input format: {fmt}")


def _normalize_format(input_format: str) -> str:
    mapping = {
        "csv": ".csv",
        "tsv": ".tsv",
        "parquet": ".parquet",
        "npy": ".npy",
        "npz": ".npz",
    }
    try:
        return mapping[input_format]
    except KeyError as exc:
        raise ValueError(f"Unknown input format: {input_format}") from exc


def _array_to_frame(array: np.ndarray) -> pd.DataFrame:
    if array.ndim != 2:
        raise ValueError("Input arrays must be 2D with shape (observations, features).")
    columns = [f"feature_{idx}" for idx in range(array.shape[1])]
    return pd.DataFrame(array, columns=columns)
