@echo off
python -m topology_engine.cli analyze examples\iris_demo.csv --label-column species --output-dir outputs\demo_run --json
