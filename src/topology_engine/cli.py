from __future__ import annotations

import argparse
import json
from pathlib import Path

from topology_engine.analysis import analyze_dataset
from topology_engine.config import AnalysisConfig
from topology_engine.io import load_input


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tda", description="Universal topological analyzer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser("analyze", help="Analyze a matrix-shaped dataset")
    analyze.add_argument("input")
    analyze.add_argument("--input-format", default="auto", choices=["auto", "csv", "tsv", "parquet", "npy", "npz"])
    analyze.add_argument("--label-column")
    analyze.add_argument("--id-column")
    analyze.add_argument("--embedding", default="pca", choices=["none", "pca", "umap"])
    analyze.add_argument("--metric", default="euclidean", choices=["euclidean", "correlation", "cosine"])
    analyze.add_argument("--max-dim", type=int, default=1, choices=[1, 2])
    analyze.add_argument("--sample-size", type=int, default=2000)
    analyze.add_argument("--n-null", type=int, default=32)
    analyze.add_argument("--null-model", default="feature-permute", choices=["feature-permute", "row-bootstrap", "distance-shuffle"])
    analyze.add_argument("--output-dir", type=Path, default=Path("outputs") / "latest_run")
    analyze.add_argument("--report-format", default="both", choices=["folder", "pdf", "both"])
    analyze.add_argument("--json", action="store_true", help="Write summary JSON and print JSON to stdout")
    analyze.add_argument("--seed", type=int, default=42)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "analyze":
        frame = load_input(args.input, input_format=args.input_format)
        config = AnalysisConfig(
            embedding=args.embedding,
            metric=args.metric,
            max_dim=args.max_dim,
            sample_size=args.sample_size,
            n_null=args.n_null,
            null_model=args.null_model,
            label_column=args.label_column,
            id_column=args.id_column,
            output_dir=args.output_dir,
            report_format=args.report_format,
            create_json=args.json,
            random_seed=args.seed,
        )
        result = analyze_dataset(frame, config)
        if args.json:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print("Topological Summary")
            print("-------------------")
            for key, value in result.metrics.items():
                print(f"{key}: {value:.4f}")
            print(f"Artifacts: {result.artifact_paths}")


if __name__ == "__main__":
    main()
