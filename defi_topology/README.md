# DeFi Higher-Order Topology — hardened research package

Computational topology (simplicial complexes, persistent homology) applied to DeFi
liquidity-pool structure through systemic stress events. Undergraduate research project.

This directory contains the original MVP **plus** the hardened build that implements the
blueprint's method section and the RESULTS "next steps", and re-runs the USDC-depeg study
with proper inference.

## Read in this order

1. `blueprint_v2.md` — the research plan.
2. `RESULTS.md` — findings from the first (MVP) run.
3. `METHODS.md` — **what the hardened build adds, and how it refines/overturns those
   findings.** Start here for anything new.

## Files

| File | What it is |
|---|---|
| `blueprint_v2.md` | Research plan (v2). |
| `RESULTS.md` | Original MVP findings (n=1, USDC depeg). |
| `METHODS.md` | Hardened-build methods, findings, and literature check. |
| `pipeline_original.py` | The MVP pipeline (diff baseline). |
| `pipeline.py` | Hardened pipeline: gap-fill, B₂, LP fork, coverage guard. |
| `inference.py` | Placebo-window permutation test + block-bootstrap CIs. |
| `robustness.py` | Threshold × window × LP-fork sweep. |
| `make_series.py` | Build a long continuous daily series for the placebo test. |
| `_fetch.py` | Standalone chart-cache warmer (run once). |
| `tests/test_toy.py` | Hand-checkable topology validation. |
| `*_series.json` | Generated observables (reproducible evidence). |

## Quickstart

```bash
pip install --break-system-packages gudhi matplotlib
python _fetch.py                                   # warm ~600-pool chart cache (once)
python -m pytest tests/test_toy.py -q              # 8/8 topology assertions
python pipeline.py --event 2023-03-11 --placebo 2023-06-15 --tag usdc_resolved
python make_series.py --start 2022-06-01 --end 2023-12-31 --out long_series.json
python inference.py long_series.json --event 2023-03-11 --metric essB1
python robustness.py --event 2023-03-11 --placebo 2023-06-15
```

`charts/` (the per-pool cache) and generated `*.png` figures are git-ignored; series JSONs
are committed as evidence.

## Headline of the hardened run

Against a **520-window placebo distribution**, the USDC-depeg window is unremarkable on
every topological observable (essB₁ at the 48.8th percentile, p ≈ 0.98). The data-gap fix
removes an artifact that had inflated the original "destabilization" reading, and the
H₀ signal does not survive a proper placebo. The LP-resolution fork is provably inert on
the survivor universe (0 / 602 pools embed the 3CRV basket). The two robust results are
the **methodological** one (persistence landscapes ≈ 0 on this complex) and the
**structural/survivorship** ceiling. See `METHODS.md` for the full table and caveats.

## The one honest caveat to carry into every claim

Only ~12.5% of today's stablecoin pools existed at the depeg date, and that is an *upper
bound* on usable history — delisted pools are unrecoverable from this API. All findings are
survivor-conditional.
