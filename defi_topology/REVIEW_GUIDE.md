# Reviewer's guide — `defi_topology/`

Branch: `claude/research-idea-feedback-yir8p7`. ~1,640 lines of Python across 12 files,
plus generated evidence (JSON), docs, and the preprint. This orients a reviewer to what
each file does, how the data flows, and — most importantly — **where a bug would change a
claim in the paper**, so the review can focus there.

The project has two reconstruction paths that share one topology core: a **survivor-only**
path (today's DeFiLlama registry, `pipeline.py` + friends — the hardened MVP) and the
**de-censored** path (Internet-Archive registry snapshots, `decensor.py` — the v2 paper).
Read `DECENSORING.md` first for the v2 findings.

Setup (both paths, no auth):
```bash
python -m venv venv && source venv/bin/activate   # do not use --break-system-packages
pip install -r requirements.txt
python -m pytest tests/test_toy.py -q     # or: python tests/test_toy.py
```

## Data flow

```
                       ┌─ survivor path (hardened MVP) ─────────────────────────────┐
_fetch.py ─> charts/<pool>.json ─> pipeline.py: load_charts()+forward_fill()
                                    +repair_universe_dips() ─> build_complex()/day_metrics()
                                        │
              make_series.py / baselines.py / landscapes.py / robustness.py
              long_series.json / baseline_long.json / landscape_audit.json
                                        └─> inference.py (placebo permutation + bootstrap)

                       ┌─ de-censored path (v2, THE PAPER) ─────────────────────────┐
web.archive.org ─> archive/<ts>.json ─> decensor.py: observables(resolve=T/F),
   (registry snapshots)                   repair_transient_dips(), 2×2, event tests
                                        └─> decensor_series.json ─> decensor_fig.py,
                                                                    paper_figures.py

both ─> paper/main.tex  (Table 1 = 2×2; Fig 1-3; numbers trace to DECENSORING.md/METHODS.md)
```

## The code (what to review)

| File | Lines | Role |
|---|---:|---|
| **`pipeline.py`** | 347 | **Topology core.** `build_complex` (the nerve), `day_metrics` (observables), `resolve_tokens` (LP fork), `forward_fill` (zero/gap fill), `repair_universe_dips` (daily transient-dip guard), `window`, survivorship. Imported everywhere. |
| **`decensor.py`** | 247 | **v2 engine.** Wayback fetch/cache (`closest_snapshot`, `fetch_registry`), `observables(resolve=…)`, `build_series` (the de-censored 2×2), `repair_transient_dips` + integrity scan. |
| `baselines.py` | 200 | Seven pairwise 1-skeleton graph metrics + RQ3 permutation; runtime `selfcheck` that the graph == the complex's 1-skeleton. |
| `inference.py` | 194 | `placebo_permutation` (event test) + `block_bootstrap_ci`. Pure stats. |
| `landscapes.py` | 151 | Exact landscape norms; verifies "H₁ all-essential → landscapes ≡ 0". |
| `paper_figures.py` | 149 | Fig 2 (representation) + Fig 3 (Curve artifact). |
| `robustness.py` | 71 | Sweep over dust cap × window × LP fork (survivor). |
| `decensor_fig.py` | 80 | Fig 1 (survivorship). |
| `make_series.py` | 49 | Build the long survivor daily series for the placebo test. |
| `_fetch.py` | 54 | Survivor chart-cache warmer. |
| `tests/test_toy.py` | 101 | Hand-checkable topology validation (8 cases). |
| `pipeline_original.py` | 196 | Pre-hardening MVP — **diff baseline only, not for review.** |

## Where bugs would matter most (suggested review priority)

Load-bearing for the paper's claims; a defect here moves a number in the abstract.

1. **`pipeline.build_complex` / `day_metrics` (nerve + persistence).** Each pool inserts a
   *filled* simplex at `f = -log10(share)`; loops are coverage holes. Check vertex-id
   `setdefault`, the `edges` set, `make_filtration_non_decreasing`,
   `compute_persistence(persistence_dim_max=True)`, `betti_numbers` padding to `[B0,B1,B2]`.
   Anchor: `tests/test_toy.py` independently pins B0/B1/B2, cycle rank and gap on six
   hand-worked complexes (incl. tetrahedron boundary with B₂=1).
2. **`decensor.observables` + `resolve_lp` (the 2×2, Table 1).** Same nerve construction on
   an archive snapshot, with `resolve=True` expanding 3CRV → {DAI,USDC,USDT}. The paper's
   central claim — the higher-order fraction swings 0.31–0.93 — rides on this. Confirm the
   3CRV address, that resolution has no collisions, and that lp_vertex/resolved differ only
   by this expansion. **NB:** unlike the survivor registry (where the LP fork is a no-op
   because 0 metapools survive), on the archive ~68 metapools per snapshot make it the
   *dominant* driver — the opposite of the MVP claim, by design.
3. **`inference.placebo_permutation` — exchangeability.** Full-length windows, fully
   disjoint from the event (`|c−ev| > 2·half`); `n_disjoint_equivalent` reports the honest
   effective sample. Known failure: non-stationarity at the series edge makes the *Terra*
   percentiles invalid (documented, not used). Verify two-sided p and `p_value_floor = 1/n`.
4. **The data-quality guards (both paths).** `decensor.repair_transient_dips` (archive) and
   `pipeline.repair_universe_dips` (daily) must flag only whole days whose *universe* TVL
   craters-and-recovers, then repair the dipped pools — so a real gradual depeg is never
   touched. This is what dissolves the spurious Curve "signal" (Fig 3); confirm the
   integrity threshold and that the event windows contain no flagged days.
5. **`baselines.selfcheck`.** Asserts graph (V,E) and components == the complex's 1-skeleton
   and B₀ — the guarantee RQ3 is apples-to-apples. Confirm it runs (and the sampled version
   in `build_range`).
6. **Filtration direction.** `-log10(share)` ⇒ high-share pools enter first; the landscape
   claim depends on this. `landscapes.py` counts finite vs infinite H₁ bars.

## Already-known limitations (please don't re-report)

Documented in `DECENSORING.md`/`METHODS.md` and the paper: findings are survivor- and
convention-conditional; **two defensible LP conventions with no tie-breaker** (0.31–0.93
range); Terra predates the archive; archive cadence is weekly not daily; Ethereum
stablecoins only. Curated defaults worth a comment but not bugs: `MINSHARE=1e-5`,
`max_gap=3`, `LP_BASES` = {3CRV}, integrity thresholds (`tvl_frac=0.6`, `pool_frac=0.5`).

## Docs, evidence, paper (context, not code review)

- `blueprint_v2.md` — plan. `RESULTS.md` — MVP findings. `METHODS.md` — hardened findings.
  `DECENSORING.md` — **v2 findings (start here).** `README.md` — orientation.
- `long_series.json`, `baseline_long.json`, `landscape_audit.json`, `decensor_series.json`
  — regenerated evidence; safe to delete and rebuild.
- `paper/main.tex` (+ `main.pdf`, 3 figures) — the preprint.
