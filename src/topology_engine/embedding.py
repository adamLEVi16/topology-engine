from __future__ import annotations

import numpy as np
from sklearn.decomposition import PCA


def compute_embedding(
    matrix: np.ndarray,
    method: str = "pca",
    n_components: int = 15,
    random_seed: int = 42,
) -> tuple[np.ndarray, dict[str, object]]:
    method = method.lower()
    if method == "none":
        return matrix, {"method": "none", "n_components": int(matrix.shape[1])}

    if method == "pca":
        n_components = max(2, min(n_components, matrix.shape[0], matrix.shape[1]))
        model = PCA(n_components=n_components, random_state=random_seed)
        embedded = model.fit_transform(matrix)
        explained = float(np.sum(model.explained_variance_ratio_))
        return embedded, {
            "method": "pca",
            "n_components": n_components,
            "explained_variance": explained,
        }

    if method == "umap":
        try:
            import umap
        except ImportError as exc:
            raise ValueError("UMAP requested but umap-learn is not installed.") from exc
        n_components = max(2, min(10, matrix.shape[1]))
        model = umap.UMAP(
            n_components=min(3, n_components),
            metric="euclidean",
            random_state=random_seed,
        )
        embedded = model.fit_transform(matrix)
        return embedded, {
            "method": "umap",
            "n_components": int(embedded.shape[1]),
            "explained_variance": None,
        }

    raise ValueError(f"Unsupported embedding method: {method}")
