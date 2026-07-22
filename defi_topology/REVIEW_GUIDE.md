# Reviewer's guide — `defi_topology/`

Branch: `claude/research-idea-feedback-yir8p7`. ~1,420 lines of Python across 10 files,
plus generated evidence (JSON), docs, and the preprint. This orients a reviewer to what
each file does, how the data flows, and — most importantly — **where a bug would change a
claim in the paper**, so the review can focus there.

Everything runs from the free DeFiLlama API (no auth). Setup:
```bash
pip install --break-system-packages gudhi matplotlib numpy
python _fetch.py                          # warm the ~600-pool chart cache (once, ~3 min)
python -m pytest tests/test_toy.py -q     # or: python tests/test_toy.py
```

## Data flow

```
_fetch.py ──> charts/<pool>.json   (per-pool daily TVL)  + charts/universe.json (registry)
                    │
   pipeline.py  ────┤  universe() / fetch_charts() / load_charts()+forward_fill()
                    │  build_complex() → day_metrics() → window() → <tag>_series.json, .png
                    │
     ┌──────────────┼───────────────┬────────────────┬───────────────┐
 make_series.py  baselines.py    landscapes.py     profile.py     robustness.py
 long_series.json  baseline_long   landscape_audit   rq1_profile     (prints table)
     │             .json+RQ3 table  .json             .json+figure
     └──> inference.py  (placebo permutation + block bootstrap on any *_series.json)
                    │
              paper/main.tex   (every number traces to METHODS.md → one of the above)
```

## The code (what to review)

| File | Lines | Role |
|---|---:|---|
| **`pipeline.py`** | 316 | **Core.** Registry, chart caching, `forward_fill` (gap repair), `resolve_tokens` (LP fork), `build_complex` (the nerve), `day_metrics` (observables), `window` (coverage guard), survivorship, plotting. Everything else imports this. |
| `inference.py` | 179 | `placebo_permutation` (the event-study test) and `block_bootstrap_ci`. No topology — pure stats on a series. |
| `baselines.py` | 190 | Seven pairwise 1-skeleton graph metrics + the RQ3 head-to-head permutation. Contains a runtime `selfcheck` that the graph equals the complex's 1-skeleton. |
| `landscapes.py` | 152 | Exact persistence-landscape norms; verifies the "H₁ is all-essential → landscapes ≡ 0" claim. |
| `profile.py` | 117 | RQ1 threshold-profile figure (`figs/rq1_profile.png`). |
| `robustness.py` | 71 | Sweep over dust cap × window size × LP fork. |
| `make_series.py` | 46 | Build one long continuous daily series for the placebo test. |
| `_fetch.py` | 51 | Standalone chart-cache warmer. |
| `tests/test_toy.py` | 101 | Hand-checkable topology validation (see below). |
| `pipeline_original.py` | 196 | The pre-hardening MVP, kept **only as a diff baseline** — not for review. `git diff` it against `pipeline.py` to see every change. |

## Where bugs would matter most (suggested review priority)

These are load-bearing for the paper's claims; a defect here moves a number in the abstract.

1. **`pipeline.build_complex` / `day_metrics` (nerve + persistence).** Each pool inserts a
   *filled* simplex on its token set at filtration `f = -log10(share)`; loops are coverage
   holes. Check: vertex-id assignment via `setdefault`, the `edges` set, `make_filtration_
   non_decreasing`, `compute_persistence(persistence_dim_max=True)`, and the `betti_numbers`
   padding to `[B0,B1,B2]`. The whole event study rides on these being right. Anchor:
   `tests/test_toy.py` independently pins B0/B1/B2, skeleton cycle rank, and the gap on six
   hand-worked complexes (hollow vs filled triangle, square, tetrahedron boundary with
   B₂=1, two components) — a reviewer should sanity-read those expected values.
2. **Filtration direction & the essential-class claim.** `-log10(share)` means high-share
   pools enter first (low ε). The paper's methodological claim ("all H₁ essential →
   landscapes ≡ 0") depends on this being the intended semantics. `landscapes.py` counts
   finite vs infinite H₁ bars; confirm the split is computed correctly.
3. **`inference.placebo_permutation` — exchangeability.** Windows slide across a 632-day
   series; placebo windows must be full-length and fully disjoint from the event window
   (centers within `2*half` of the event are excluded — fixed after external review; see
   METHODS.md §2.10), and `n_disjoint_equivalent` reports the autocorrelation-honest
   effective sample. The **known failure mode is non-stationarity at the series edge**
   (universe grows 45→96 pools), which makes the *Terra* percentiles invalid — this is
   documented and the paper does not use them. Verify the two-sided p and the
   `p_value_floor = 1/n` guard. For USDC (mid-series) the test is used.
4. **`forward_fill` semantics.** Bridges interior gaps (absent samples or one-day zeros
   between positives) up to `max_gap=3`, within a pool's active span; does not resurrect a
   truly dead pool. Check the active-span boundaries and that it can't fill across a genuine
   death > 3 days. This fix removed the 2023-02-11 artifact.
5. **`baselines.selfcheck`.** Asserts the graph's (V, E) and component count equal the
   complex's 1-skeleton and B₀ — the guarantee that RQ3's "pairwise vs topology" is
   apples-to-apples. Confirm the assertion is real and runs.
6. **`resolve_tokens` (LP fork).** Collapses a recognised basket only on a *strict* subset
   (metapool), leaving the bare 3pool intact. Empirically a no-op on all real data (0/~600
   pools) — the toy test exercises the non-trivial path.

## Already-known limitations (please don't re-report)

Documented in `METHODS.md` and the paper's Limitations section: survivorship (7.5–12.5%
upper bounds), N=2 events, single chain, the LP fork being untestable on real data, and the
methodological caveat being "expected, not deep." Curated defaults worth a comment but not
bugs: `MINSHARE=1e-5` dust cap, `max_gap=3`, the `LP_BASES` map (3CRV only).

## Docs, evidence, paper (context, not code review)

- `blueprint_v2.md` — research plan. `RESULTS.md` — original MVP findings. `METHODS.md` —
  hardened findings with every cited number. `README.md` — orientation.
- `*_series.json`, `baseline_long.json`, `landscape_audit.json`, `rq1_profile.json` —
  regenerated evidence; safe to delete and rebuild.
- `paper/main.tex` (+ `main.pdf`) — the preprint; numbers trace back to `METHODS.md`.
