# Hardened pipeline — methods, findings, and what changed

This documents the extended build (`pipeline.py`, `inference.py`, `robustness.py`,
`make_series.py`, `tests/test_toy.py`) that implements the blueprint-v2 method section
and the RESULTS.md "next steps 1–4". It **refines, and in two places overturns, the
original findings** — read `RESULTS.md` first, then this.

Everything here is reproduced from the free DeFiLlama API (602-pool Ethereum stablecoin
universe) and the cached charts. All commands below run from `defi_topology/`.

```bash
pip install --break-system-packages gudhi matplotlib
python _fetch.py                                   # warm the chart cache (~600 pools, once)
python -m pytest tests/test_toy.py -q              # topology correctness on hand-checked complexes
python pipeline.py --event 2023-03-11 --placebo 2023-06-15 --lp resolved --tag usdc_resolved
python make_series.py --start 2022-06-01 --end 2023-12-31 --out long_series.json
python inference.py long_series.json --event 2023-03-11 --metric essB1 --half 30
python robustness.py --event 2023-03-11 --placebo 2023-06-15
```

---

## 1. What was added (maps to blueprint §6 + RESULTS "next steps")

| Piece | File | Blueprint item |
|---|---|---|
| Data-gap forward-fill | `pipeline.forward_fill` | fixes a bug not previously caught |
| B₂ reporting + skeleton-vs-nerve as headline | `pipeline.day_metrics` | §6.2, §6.3 |
| LP-resolution fork (resolved / lp_vertex) | `pipeline.resolve_tokens` | §6.1, mentor Q1 |
| Placebo-window permutation test | `inference.placebo_permutation` | §7, next-step 2 |
| Block-bootstrap CIs | `inference.block_bootstrap_ci` | §7 |
| Threshold/window/fork robustness sweep | `robustness.py` | §8, next-step 3 |
| Hand-checkable toy-complex validation | `tests/test_toy.py` | Week 3–5 milestone |

The observables reduce to the originals when `lp_mode="resolved"`, `coverage_frac=0`,
`--no-fill` — this is a strict superset of `pipeline_original.py`.

---

## 2. Findings

### 2.1 The 2023-02-11 "essB₁ = 0" was a data artifact, and fixing it makes finding 2 *weaker*

That day lost ~16 pools to missing chart samples (`pools` 68→52), collapsing the complex
and reading essB₁ = 0. `forward_fill` bridges short interior holes (absent samples or
one-day zeros between positive values, ≤ 3 days) within a pool's active span. After the
fix, 2023-02-11 reads essB₁ = 4 like its neighbours and **no days are dropped**.

Consequence: the event-window essB₁ standard deviation falls from **0.72 → 0.38**. The
original finding 2 read the event window as showing "modest lift **and destabilization**".
Roughly half of that "destabilization" was the single artifact day. The lift itself was
never event-locked — essB₁ steps 4→5 on **2023-02-20, 19 days before the depeg**, and is
flat through March 10–13.

### 2.2 B₂ = 0 is now verified, not assumed

Across the whole event window (and the 579-day long series), B₂ ≡ 0. The blueprint
predicted this (§6.0); it is now checked. `tests/test_toy.py` confirms the code *can*
detect B₂ = 1 (tetrahedron boundary / S²), so the zero is real, not a blind spot.

### 2.3 The LP-resolution fork is empirically inert on any survivor-reconstructed universe

`resolve_tokens(..., "lp_vertex")` re-collapses a recognised LP basket (3CRV =
{DAI,USDC,USDT}) into one vertex when it appears as a **strict** subset of a larger pool
(a metapool). The toy test proves the mechanism: a FRAX/3CRV metapool is a filled
tetrahedron under `resolved` (gap = 3) and a single FRAX–3CRV edge under `lp_vertex`
(gap = 0).

But on the real data the two modes are **identical in every run and every robustness
cell**, because:

- **0 of 602** of today's pools contain {DAI,USDC,USDT} as a strict subset;
- only **4 survivor pools** are *exactly* the bare 3pool (not metapools);
- the classic 3pool-metapools (FRAX3CRV, MIM3CRV, …) the fork targets are **delisted** —
  they are exactly the pools survivorship removes.

**This collapses blueprint mentor-question 1 for the historical study:** LP-vertex vs
resolved is not a choice you can make from registry reconstruction, because the pools that
would distinguish the two forks did not survive. Studying it requires archival registry
snapshots or on-chain data (Dune/subgraphs) — the dependency §5 deferred.

### 2.4 Against a proper placebo distribution, no observable makes the depeg window abnormal

> **[Superseded]** The numbers in this subsection are from the first run (520 placebo
> windows, 2022-06–2023-12 span, pre-correction test). The canonical current values —
> longer span, and the corrected event-disjoint/full-window test from the external code
> review — are in §2.7 and §2.10. The conclusion is unchanged.

The original "matched control" was the **adjacent** pre-event window (Dec 12–Feb 10),
i.e. the same continuous series, sharing dates with the event window. Replaced with a
placebo-window permutation test: slide the [−30,+30] window across every non-overlapping
center in a 579-day baseline (2022-06 … 2023-12) and locate the event window in that
distribution of **520 placebo windows**.

| metric | event | placebo mean [min,max] | event percentile | two-sided p |
|---|---|---|---|---|
| essB₁ | 4.82 | 6.25 [3, 12.1] | **48.8%** | **0.98** |
| gap | 11.82 | 11.17 [9.6, 13.1] | 80.4% | 0.39 |
| tp0 (H₀) | 2.06 | 2.39 [1.83, 3.67] | 38.5% | 0.77 |

The event window sits essentially at the **median** of the placebo distribution for
essB₁. The H₀ signal (original finding 3) — which looked real against the January control
— **does not survive**: at the 38th percentile it is unremarkable. Block-bootstrap 95% CIs
(circular block = 10) are tight because the series is near-constant: essB₁ [4.54, 5.00],
gap [11.54, 12.00], tp0 [1.95, 2.15].

Honesty diagnostic built into `inference.py`: over 579 days essB₁ takes **11 distinct
values with a longest constant run of 153 days**; gap takes 7 values, longest run 215.
The object is close to piecewise-constant, which is *why* no event test resolves — and the
`p_value_floor` field reports the smallest achievable p (1/520) so the test cannot
over-claim.

### 2.5 The landscape claim is verified exactly — and upgraded (`landscapes.py`)

RESULTS.md finding 1 claimed landscapes are "~0" because every H₁ class is essential.
`landscapes.py` now verifies this by direct computation of H₁ persistence diagrams and
exact landscape norms (grid-integrated, no external deps):

- **Zero finite H₁ bars on all 579 days, 2022-06-01 → 2023-12-31.** Not one loop class
  is ever closed by a weaker pool across 19 consecutive months. Under the standard
  discard-infinite convention (gudhi/persim default; the Gidea–Katz pipeline), the H₁
  landscape is **identically zero** — L1 = L2 = L∞ = 0 exactly, every day.
- **The truncation escape hatch doesn't rescue it.** Capping infinite bars at a cutoff
  makes norms nonzero (L2 ≈ 1.2–1.4) but the value tracks the arbitrary cutoff choice
  (fmax vs dust-cap ceiling shift it ~10%), and event vs placebo truncated norms are
  statistically indistinguishable anyway (mean L2 1.22 vs 1.25).
- **Control for "broken machinery":** H₀ has genuine finite bars and nonzero landscapes
  (L2 mean 0.62 event / 0.46 placebo), so the computation is fine — the degeneracy is a
  property of H₁ on this object.

Preprint phrasing this supports: *"On share-filtered structural liquidity complexes the
persistence-landscape summary is identically zero in H₁; the return-space TDA toolkit
does not transfer."* Evidence: `landscape_audit.json`.

### 2.6 Robustness: the (non-)result is stable, the levels are not

Across 3 dust caps × 3 half-windows × 2 LP forks: the event-window essB₁ is **≤ the
placebo in all 18 cells**, lp_vertex ≡ resolved in all 18, and 0 days are dropped. The
absolute levels *do* move with the dust cap (essB₁ 4.82 at 1e-5 → 6.82 at 1e-6), so any
paper must report the threshold — but the qualitative conclusion (event window not
anomalous) is invariant to all three knobs.

---

### 2.7 The pairwise baseline closes RQ3: nothing structural moves, at any order (`baselines.py`)

RQ3 is a *relative* claim ("beyond pairwise"), so the pairwise side is now computed on
exactly the same construction — the graph IS the 1-skeleton of the day's complex (asserted
by a runtime selfcheck on V, E, and B₀). Seven graph metrics (E, density, components,
transitivity, spectral radius unweighted and share-weighted, degree dispersion) go through
the identical placebo-window permutation as the topology, over the same 632-day series:

| metric (kind) | event percentile | p |
|---|---|---|
| E, density, n_comp, transitivity, spec_rad, w_spec_rad, deg_cv (graph) | 34–63% | 0.67–0.91 |
| essB₁, gap, tp0, B₀ (topology) | 31–84% | 0.32–0.91 |

(Values under the corrected event-disjoint, full-window test of §2.10: 451 sliding
placebos, ≈7 disjoint-equivalent.)

**The USDC-depeg window is unremarkable on every metric of either kind.** The honest RQ3
answer is therefore symmetric: it is not that topology fails where graphs succeed — the
share-filtered co-membership structure is event-invariant at *every* order. What moves in
a depeg is prices and flows, not structure. (Registry-drift note: the refreshed cache has
599 vs 602 pools and the series now starts 2022-04-09; essB₁'s event percentile moved only
48.8 → 53.6 — the null is stable under drift.)

### 2.8 RQ1 measured: most loop structure is higher-order fills, and the fraction is falling (`profile.py`)

The threshold-profile figure (`figs/rq1_profile.png`, the paper's central descriptive
figure) sweeps the share threshold at five snapshot dates. At the operating threshold
(1e-5), the fraction of 1-skeleton loops filled by ≥3-asset pools is:

| 2022-05-10 | 2022-09-15 | 2023-03-11 | 2023-06-15 | 2023-12-15 |
|---|---|---|---|---|
| 77% | 69% | 71% | 64% | 52% |

Two content claims: (i) **in the survivor-reconstructed universe, the majority of loop
structure is genuinely higher-order** — the multi-way rhetoric is right about *composition*
even though the object is dynamically inert; (ii) the fill fraction **trends down 77% →
52%** over 19 months (not strictly monotonic), consistent with blueprint §6.0's
metapool-era → pair-era hypothesis. Both claims are survivor-conditional: multi-asset
survivors (3pool and kin) are old, large pools, so the level is likely biased up; the
*trend* direction is the more defensible statement.

### 2.9 Terra/UST: worse survivorship, perfect rigidity, and a placebo-test trap caught

- **Survivorship 7.5%** (45/599 pools live on 2022-05-10), worse than USDC's 12.5%, as
  predicted; the signal-bearing pools (UST, Anchor-adjacent) are delisted and invisible.
- **The reconstructable structure is perfectly rigid through the crash: essB₁ = 3 and
  cycle rank = 13 on all 61 days** of the window while universe TVL fell **52%**
  ($11.4B → $5.5B). This upgrades the rigidity result: not even the largest collapse in
  DeFi history moves a single loop of the survivor-reconstructed complex. Only tp0 drifts
  (≈2.9 → 2.6 through crash week — mild merging), consistent with H₀ being the only
  live dimension.
- **Do not use the placebo percentiles for Terra.** The naive test returns "significant"
  extremes (essB₁ 0th percentile; several graph metrics at the empirical floor, p < 0.003
  under the corrected §2.10 test) — but the Terra window
  sits at the series' left edge and the universe grows monotonically (45 → 96 pools over
  the span), so every size-correlated metric is mechanically extreme vs later placebos.
  Exchangeability fails at the edge of a nonstationary series; these are trend artifacts,
  not event effects, and the write-up must say so. The valid Terra evidence is the
  within-window dynamics — which are flat.

### 2.10 External code review: one real bug fixed, one claim refuted empirically

An independent review (Gemini) of the codebase produced two HIGH-priority findings.

**Valid — placebo windows could overlap the event window (fixed).** The exclusion rule
`|c − ev| < half` admitted placebos sharing up to `half` days with the event window.
Overlapping placebos are dragged toward the event statistic and pad the middle of the
reference distribution — a bias *toward* the null we claim, so it mattered. Fix
(`inference.py`): placebos must now be fully disjoint from the event window
(`|c − ev| > 2·half`) and all windows (event and placebo) must be full-length, which
also evicts truncated series-edge windows from the reference distribution. A new
`n_disjoint_equivalent` diagnostic reports the autocorrelation-honest effective sample
(451 sliding placebos ≈ 7 disjoint-equivalent for the 632-day series). Rerun deltas:
USDC essB₁ 53.6→54.5th pct (p 0.93→0.91), gap 82.2→84.0 (p 0.36→0.32), tp0 34.9→30.8
(p 0.70→0.62); graph metrics 34–63rd pct. **Conclusion unchanged — the null survives
its own audit.** Terra's invalid extremes became more extreme (empirical-floor p),
reinforcing §2.9's warning.

**Refuted — `initialize_filtration()` "must be called" before persistence.** Tested
three ways on gudhi 3.13: (i) the API itself emits *"Since Gudhi 3.2, calling
SimplexTree.initialize_filtration is unnecessary"*; (ii) an adversarial insertion-order
complex (triangle inserted at high filtration, faces lowered afterwards) reproduces the
hand-computed diagram exactly (H₁ bar (1.5, 3.0)) without it; (iii) on real days
(2023-03-11, 2022-05-10, 2023-12-15) inserting pools in ascending vs descending share
order yields identical Betti numbers and H₀ persistence, matching the pipeline. The
finding reflects pre-3.2 documentation.

Minor items adopted: fetch-failure logging (`_fetch.py`); sampled skeleton selfcheck
during the long-series build and a cached-span mismatch warning (`baselines.py`).
Declined: replacing the union-find's iterative path-halving with recursion — the
implementation is correct (every node is queried through `find`), and recursion adds a
depth limit for zero benefit.

## 3. Literature check (blueprint §4)

- **arXiv:2607.10943 (Forte 2026), "It Takes Two to Tango…"** — **verified real and
  characterised correctly.** Central Bank of Argentina credit-registry data (Aug 2023–Dec
  2025), adjusted H-eigenvector centrality on hypergraphs; TradFi credit, *not* persistent
  homology, *not* DeFi. The §4 framing stands.
- **Add two citations you are currently missing:**
  - *Network Analysis of Uniswap* (arXiv:2503.07834) — tokens as nodes, pools as edges.
    This is **exactly the pairwise-graph baseline** your skeleton-vs-nerve decomposition
    sits on top of; you must cite and differentiate from it.
  - *Mapping Microscopic and Systemic Risks in TradFi and DeFi: a literature review*
    (arXiv:2508.12007) — positions the contribution.
- **Return-space crypto/FX TDA is saturated**, consistent with §4 (e.g. FX co-movement
  persistent homology, arXiv:2510.19306).
- A first-pass search found **no persistent-homology / nerve-complex treatment of DeFi
  liquidity structure** — the structural corner does appear open. This is a first pass,
  not the §7 systematic review.

---

## 4. Honest bottom line (what this does to the paper)

With the pipeline hardened, the RQ3 answer sharpens from RESULTS.md's "leaning against the
headline hypothesis" to: **no observable — topological or pairwise-graph — distinguishes
the largest stablecoin depeg on record from typical placebo windows, robustly across
thresholds, windows, and both LP forks; and the reconstructable structure is perfectly
rigid even through Terra's 52% TVL collapse.** The compensating positive is §2.8: RQ1 has
a real descriptive answer (a majority of loop structure is higher-order fills, with a
declining trend) — the composition claim survives even though the dynamics claim dies. Two of the original three empirical findings weaken (finding 2's
destabilization was partly an artifact; finding 3's H₀ signal does not survive a real
placebo). The two strongest results are unchanged and now better supported:

1. **methodological** — persistence landscapes/L^p are ~0 on this complex (every H₁ class
   is essential); the return-space TDA toolkit does not transfer to structural liquidity
   complexes; and
2. **structural/survivorship** — the reconstructable object is near-static (essB₁: 11
   states, 153-day runs), and survivorship (12.5% upper bound) is severe enough that it
   even **erases a headline design fork** (§2.3).

This points toward the sparsity/methodological paper the blueprint already names as its
honest fallback (§3, §8). That reframe is a call for you and your mentor — this build does
not assume it; it just makes the evidence for it airtight.

## 5. Limitations of this build

- Placebo windows are drawn from a single 18-month span and remain **survivor-conditional**
  — the permutation distribution is "typical *reconstructable* windows", not ground truth.
- Still N = 1 event. The machinery is ready for Terra, but Terra survivorship will be worse
  and the signal-bearing pools (UST/Anchor) are precisely the delisted ones.
- `forward_fill` max_gap = 3 and the LP basket map (3CRV only) are curated defaults;
  both are single lines to extend.
- The LP fork is validated by construction (toy test) but **cannot be exercised on real
  data** from this source (§2.3).
