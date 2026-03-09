# Topology Engine

`topology_engine` is a library-first universal topological analyzer for matrix-shaped datasets.

It accepts tabular and array-like inputs, preprocesses them, computes a low-dimensional embedding, runs persistent homology, evaluates permutation-based significance, and writes a portfolio of figures plus a PDF report.

## Features

- `analyze_dataset(data, config) -> AnalysisResult`
- CLI entrypoint: `tda analyze <input>` or `python -m topology_engine.cli analyze <input>`
- Supported inputs: `.csv`, `.tsv`, `.parquet`, `.npy`, `.npz`
- Fast defaults: numeric-column filtering, imputation, scaling, PCA, H0/H1 persistence
- Null-model significance with z-scores, empirical p-values, and null-distribution plots
- Figure bundle plus PDF report
- Optional grouped analysis using a label column

## Quick Start

Install the package and test dependencies:

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

Run the bundled demo dataset:

```bash
python -m topology_engine.cli analyze examples/iris_demo.csv --label-column species --output-dir outputs/demo_run --json
```

Or on Windows:

```bat
scripts\run_demo.bat
```

## Example Outputs

A successful run writes:

- `figures/embedding_overview.png`
- `figures/persistence_diagram.png`
- `figures/betti_curves.png`
- `figures/barcode_summary.png`
- `figures/metric_significance.png`
- `figures/null_distribution_topological_complexity.png`
- `figures/complexity_dashboard.png`
- `tables/metrics.csv`
- `tables/significance.csv`
- `summary.json`
- `report/topology_report.pdf`

## Running on Your Own Data

Rows are observations and columns are features. If you have metadata columns, pass them explicitly.

```bash
python -m topology_engine.cli analyze data.csv --label-column group --output-dir outputs/run1 --json
```

## Notes

- Nonnumeric columns are dropped unless named as `--id-column` or `--label-column`.
- UMAP is optional and only used if installed.
- Empirical p-values come from the chosen null model, so increasing `--n-null` improves resolution.
- The default topological complexity score is a heuristic summary for exploratory comparison.
