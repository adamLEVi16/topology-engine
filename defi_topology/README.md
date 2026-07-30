# DeFi Higher-Order Topology — research package

Computational topology (simplicial complexes, persistent homology) applied to the
structure of Ethereum stablecoin liquidity through systemic stress events. Undergraduate
research project (A. Levine, Hofstra).

The project ran in two stages. The **hardened MVP** (survivor-only) is preserved for the
record; the **de-censored v2** — which recovers the full historical universe from the
Internet Archive and is the current paper — supersedes several of its findings. Read the
docs in order and the arc is clear.

## Read in this order

1. `blueprint_v2.md` — the research plan.
2. `RESULTS.md` — findings from the first (survivor-only MVP) run.
3. `METHODS.md` — the hardened build; refines/overturns the MVP findings.
4. `DECENSORING.md` — **the v2 result. Start here for the current paper.** De-censoring
   survivorship via the archive; the higher-order fraction is a modeling artifact; the
   robust null on two events.
5. `paper/main.pdf` — the manuscript (`paper/main.tex` source).

## Files

| File | What it is |
|---|---|
| `blueprint_v2.md`, `RESULTS.md`, `METHODS.md`, `DECENSORING.md` | Plan + findings (see order above). |
| `REVIEW_GUIDE.md` | Orientation for a code reviewer. |
| `pipeline.py` | Core engine: nerve complex, share filtration, gap-fill, transient-dip repair, LP fork, observables. |
| `pipeline_original.py` | The pre-hardening MVP (diff baseline only). |
| `decensor.py` | **v2 engine.** Internet-Archive de-censoring: full historical universe, the 2×2, event tests, integrity scan + `repair_transient_dips`. |
| `inference.py` | Placebo-window permutation test + block-bootstrap CIs. |
| `baselines.py` | Pairwise 1-skeleton graph metrics + the RQ3 side-by-side table. |
| `landscapes.py` | Exact landscape-norm audit (verifies the "identically zero" claim). |
| `robustness.py` | Threshold × window × LP-fork sweep. |
| `make_series.py` | Build a long continuous daily (survivor) series for the placebo test. |
| `decensor_fig.py`, `paper_figures.py` | Generate the three paper figures. |
| `_fetch.py` | Standalone chart-cache warmer (run once). |
| `tests/test_toy.py` | Hand-checkable topology validation (8 cases). |
| `paper/` | `main.tex` + compiled `main.pdf` + the three figures. |
| `*_series.json`, `*_audit.json` | Generated evidence (safe to delete and rebuild). |
| `figs/` | Committed figures (`decensor.png`, `representation.png`, `curve_artifact.png`). |

## Quickstart

```bash
python -m venv venv && source venv/bin/activate   # do not use --break-system-packages
pip install -r requirements.txt
python -m pytest tests/test_toy.py -q            # 8/8 topology assertions

# v2 (de-censored) — the current paper
python decensor.py --build --start 2022-10-01 --end 2025-06-01 --step 30 \
    --dense-start 2023-02-01 --dense-end 2023-04-20 --dense-step 7
python decensor_fig.py                           # central survivorship figure
python paper_figures.py                          # representation + Curve-artifact figures

# hardened survivor-only baseline (corroborating)
python _fetch.py                                 # warm ~600-pool chart cache (once)
python make_series.py --start 2022-04-09 --end 2023-12-31 --out long_series.json
python inference.py long_series.json --event 2023-03-11 --metric essB1
python baselines.py --event 2023-03-11 --placebo 2023-06-15
python landscapes.py
```

`charts/` and `archive/` (the caches) are git-ignored; the small series/audit JSONs and the
three paper figures are committed as evidence.

## Headline (v2)

**Registry-based reconstruction — the field default — is severely biased, and the biases
determine the answer.** Reconstructing from pools that survive to today sees only ~1/10 of
the loop structure; Internet-Archive snapshots recover the rest. The higher-order fraction
then has *no convention-free value* — it swings **0.31–0.93** across LP-token representation
(the larger driver) × survivorship, and even its time-trend flips sign between conventions.
The one result robust to every choice (survivorship, representation, cadence) is a **null**:
through both the USDC depeg and the Curve/Vyper exploit the structure is inert — reached
only after an integrity scan removes a corrupted event-window crawl that would otherwise
read as a spurious detection. See `DECENSORING.md` and the paper.

## The one honest caveat to carry into every claim

Findings remain **survivor-and-convention conditional**, and Terra (May 2022) predates the
archive. But note what v2 changed: delisted pools are *not* unrecoverable (the earlier
"unrecoverable ceiling" framing was wrong) — true survivorship is 24–41% and is de-censored
here; the residual caveats are the two defensible LP conventions, weekly (not daily) archive
cadence, and Ethereum stablecoins only.
