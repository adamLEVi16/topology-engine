# The Higher-Order Topology of DeFi Systemic Risk — Blueprint v2

**MVP scope:** A simplicial-complex event study of stablecoin / multi-asset liquidity-pool topology through DeFi stress events, centered on the skeleton-vs-nerve loop decomposition.
**Author role:** Undergraduate research project (1st-year, Mathematical Business Economics, Hofstra University)
**Mode:** Fully online; computational topology + classical econometrics (no ML)
**Status:** v2 draft for discussion with a faculty mentor. Supersedes v1.

**Changes from v1:** citation corrected (§4); Week 0 redefined as an H₁ non-triviality test — *already executed, results in §6.0*; headline metric changed to the skeleton-vs-nerve decomposition (§6.3); TVL-confounded filtration replaced with share-based weights (§6.4); scope cut to the multi-asset-pool generator and 1–2 events; early-warning framing removed; sheaf companion note dropped.

---

## 1. One-line summary

Measure how much of the loop structure in DeFi liquidity-pool networks is genuinely higher-order (simplicial) rather than pairwise (graph-theoretic), and how that decomposition moves through systemic stress events.

## 2. Motivation and the gap

Classical financial-contagion models are pairwise: institutions are nodes, bilateral exposures are edges (Eisenberg–Noe clearing, interbank networks). But a multi-asset AMM pool like Curve's 3pool {USDC, USDT, DAI} is an inherently 3-way relationship; a graph records only its pairwise projection and discards the joint structure.

The decisive advantage of DeFi as a laboratory is **observability**: unlike TradFi, where bilateral exposures are confidential, pool compositions, reserves, and liquidations are public and machine-readable on-chain. This removes the confidentiality barrier that has always constrained structural contagion research. That — not the topology per se — is the strongest argument for this project, and the paper should lead with it.

## 3. Research questions

- **RQ1 (descriptive, primary):** How much of the cycle structure of the DeFi liquidity network is higher-order? Formally: what is the gap between B₁ of the pool-nerve complex and the cycle rank (E − V + C) of its 1-skeleton, and what economic relationships generate that gap?
- **RQ2 (dynamic):** How does this decomposition — and B₀, B₁, and persistence-landscape norms — evolve through 1–2 stress events (USDC depeg first; Terra/UST if data quality permits)?
- **RQ3 (comparative):** Do the topological features vary with events beyond what pairwise graph metrics and market baselines (volatility, mean pairwise correlation, TVL drawdown) already capture?

A rigorous negative on RQ3 is a publishable result: "higher-order structure in DeFi liquidity networks is far sparser than the multi-way rhetoric implies" is a clean finding that defines where topology adds value. The design assumes this may be the outcome.

*Cut from v1:* early-warning / prediction framing (indefensible at N ≈ 2–5 events); RQ4 motif taxonomy (folded into RQ1's "what generates the gap" question); lending-collateral and liquidation generators (deferred to future work — account-level co-collateralization data is the hardest engineering in the project and is not needed for the MVP).

## 4. Novelty positioning (corrected)

- **Higher-order financial contagion is a live, early-stage area.** arXiv:2607.10943 (Forte, 2026) provides the first hypergraph analysis of bank–firm credit networks, using Central Bank of Argentina credit-registry data and hypergraph centrality measures. **Cite precisely:** it is TradFi credit and hypergraph centrality, *not* persistent homology and *not* DeFi. It supports the claim that "higher-order beats pairwise" is an open research direction — nothing more.
- **Return-space TDA is saturated and is not this project's contribution.** Persistent homology of return point clouds now covers equities (Gidea–Katz and successors), FX, and crypto (including 2026 work applying Takens embedding + Vietoris–Rips to cryptocurrency returns). The return-space complex in §6.5 is retained only as an internal consistency check.
- **The open corner is structural:** the network-topological analysis of liquidity/collateral structure — as opposed to return co-movement — is largely unoccupied, and the skeleton-vs-nerve decomposition of RQ1 appears to be unmeasured in the literature.

## 5. Data

| Dataset | Provides | Access |
|---|---|---|
| DeFiLlama `yields.llama.fi/pools` | Full pool registry: project, chain, symbol, `underlyingTokens` (addresses), current TVL, stablecoin flag | Free, no auth |
| DeFiLlama `yields.llama.fi/chart/{pool}` | Daily historical TVL per pool | Free, no auth |
| CoinGecko / CoinMetrics | Prices, returns, market caps for baselines and the return-space check | Free tiers |
| Event references | USDC depeg (Mar 11–13, 2023); Terra/UST (May 2022); Curve/CRV (Jul 2023) as candidates | DeFiLlama hacks page + reporting |

**Key simplification (removes Dune/subgraphs from the critical path):** a pool's token set is fixed at deployment. The historical complex at date *t* is therefore today's registry **filtered to pools with TVL above threshold at t**, using the per-pool chart endpoint. Dune/The Graph are needed only for future extensions (liquidations, co-collateralization), not the MVP.

**Known limitations of this reconstruction (state in the paper):** pools deprecated and delisted from the registry before today are invisible (survivorship at the registry level); token-set fixity should be spot-checked for the specific pools driving results. Both are testable and neither blocks the MVP.

## 6. Method

### 6.0 Week-0 feasibility result (executed July 2026)

The two failure modes that would have killed the project were tested against the live DeFiLlama registry before committing to the design:

1. **Triviality:** Is H₁ identically zero (complex collapses to a cone)? **No.** On the Ethereum stablecoin universe, B₁ = 53 at TVL ≥ $100k, 19 at ≥ $1M, decaying to 0 above ~$50M. The filtration is informative.
2. **Higher-order content:** At the $100k threshold the 1-skeleton has cycle rank 64 while the nerve has B₁ = 53 — i.e., **11 of 64 independent loops (~17%) are filled in by higher simplices.** The higher-order margin exists but is thin in today's pair-dominated (Uniswap-era) DeFi. B₂ = 0 throughout.
3. Only 13 stablecoin pools with ≥3 tokens exceed $100k TVL today, dominated by the 3pool and wrapped copies of it (Convex, Aave-wrapped, iDAI), a Euro triple, and GHO baskets. **Hypothesis for the event study:** the 2022–23 Curve-metapool era should show materially richer higher-order structure than today — this is checkable and is the first thing the historical run answers.

### 6.1 Complex construction

- **Vertices:** assets, keyed by token contract address (not symbol), Ethereum mainnet for MVP.
- **Simplices (nerve):** σ = {a₀,…,a_k} is included when all assets in σ co-occur in at least one live pool at date t; downward closure taken. Pools with ≥2 tokens all contribute (2-token pools supply the edges loops run through). Faces are implications of co-membership, not separately observed bilateral exposures — maintain this distinction in interpretation.
- **The LP-token resolution decision (elevated from "resolution choice" to a design fork):** Curve metapools are {X, 3CRV}. Resolving 3CRV into {USDC, USDT, DAI} makes every metapool a simplex containing the 3pool triangle as a face — pushing the complex toward a cone (contractible, H₁ ≈ 0 by construction, not economics). **Default: keep LP tokens as their own vertices** (composability is then visible as nesting structure); report the resolved variant as a sensitivity. Justify the choice explicitly to the mentor.
- The nerve is preferred over a flag/clique complex: a flag complex fills every pairwise clique and is even more collapse-prone. (Consequence: observed loops are coverage holes, which is the economically meaningful object.)

### 6.2 Invariants

Per (t, ε): B₀ (fragmentation), B₁ (independent loops — the substrate of cyclic dependency), persistence diagrams and landscape L^p-norms across the filtration. B₂ tracked but expected ≈ 0.

### 6.3 Headline metric: the skeleton-vs-nerve decomposition

For each snapshot, report **cycle rank of the 1-skeleton (E − V + B₀) vs. B₁ of the nerve**. The difference is exactly the loop structure explained by higher-order co-occurrence — the quantity the whole "graphs discard multi-way structure" argument turns on. This makes RQ3 answerable by measurement rather than rhetoric, and it is computable at every date of the event window. The central figure of the paper is this decomposition plotted daily through the event.

### 6.4 Filtration weights (TVL confound fixed)

Raw TVL is dollar-denominated and craters mechanically during a depeg, so a TVL-filtered complex shrinks because prices fell — a laundered copy of the TVL-drawdown baseline. **Primary filtration: level-invariant weights** — a pool's share of universe TVL at date t (or token quantities where retrievable). Secondary robustness: raw-TVL filtration, reported alongside a direct control for aggregate TVL drawdown. A topological result that dies under share weighting is a price artifact, and the paper says so.

### 6.5 Return-space complex (consistency check only)

Vietoris–Rips on d_ij = √(2(1 − ρ_ij)) over rolling return correlations, same asset universe, kept strictly separate from the structural complex. Time-boxed to one week; not a contribution; cut first if the schedule slips.

## 7. Event-study design

- **Event 1 (primary): USDC depeg, March 11–13, 2023.** Cleanest event: sharp, dated, stablecoin-centered, directly hits the 3pool complex. Window [−30, +30] days, daily snapshots, matched calm-period control window.
- **Event 2 (conditional): Terra/UST, May 2022.** Added only if registry survivorship around delisted Terra-era pools proves acceptable.
- **Tracked daily:** B₀, B₁, skeleton cycle rank, the decomposition gap, landscape norms; baselines: 1-skeleton graph metrics (clustering, spectral radius, centrality dispersion), rolling volatility, mean pairwise correlation, TVL drawdown.
- **Inference:** non-parametric only — event-window vs. matched placebo-window comparisons, permutation tests, block bootstrap, and degree-preserving / hyperedge-size-preserving randomization nulls. Effect sizes and CIs, not p-value theater. **Feature set pre-registered** (B₀, B₁, decomposition gap, landscape norms) before event windows are examined.
- *Cut from v1:* Granger lead/lag and ROC-AUC logistic regression — cross-event inference machinery with no cross-event sample to run on.

## 8. Threats to validity

- **Registry survivorship:** delisted pools are invisible; quantify by checking known 2022–23 pools against the current registry before trusting the Terra window.
- **Construction sensitivity:** LP-token resolution (§6.1) and TVL-threshold choice; report both forks.
- **Window sensitivity:** robustness across 30/60/90-day rolling windows.
- **Shock-type asymmetry:** TDA literature finds topology loses lead time on sudden shocks vs. slow-burn stress; expect weaker dynamics for hack-type events. Report as a finding, not a failure.
- **Causality:** observational throughout; all claims are characterization and association.
- **Thin higher-order margin:** §6.0 shows the gap may be small. If the historical margin is also thin, the paper's honest thesis becomes the sparsity result itself.

## 9. Deliverables

Primary: a 20–30 page reproducible paper (Jupyter notebook + pipeline, git-versioned). Targets: Hofstra undergraduate research symposium; arXiv preprint (q-fin); undergraduate research journals. *Dropped from v1:* the sheaf/cohomology companion note.

## 10. Timeline (~14 weeks, part-time)

| Week | Milestone |
|---|---|
| 0 | ~~Feasibility audit~~ **Done:** H₁ non-triviality and decomposition confirmed on live data (§6.0). |
| 1–2 | Historical snapshot builder: per-pool TVL history → daily complexes for the USDC-depeg window; first pass at the decomposition time series. Survivorship audit for the Terra window. |
| 2–3 | Literature review (~15 papers: TDA-finance, contagion, higher-order networks) run in parallel; mentor meeting with this document + the Week 1–2 plot. |
| 3–5 | Harden the pipeline: share-based weights, both LP-resolution forks, persistence landscapes; validate invariants on a hand-checkable toy complex. |
| 5–7 | Full USDC-depeg run with baselines; decide Terra go/no-go. |
| 7–9 | Robustness: thresholds, windows, LP-resolution fork, permutation/bootstrap/randomization nulls. |
| 9–11 | Statistical analysis; placebo-window comparisons; effect sizes. |
| 11–13 | Draft paper and figures. |
| 13–14 | Mentor revisions; finalize notebook; symposium/arXiv prep. |

Slack is built in: the v1 timeline budgeted 3–4 weeks for Dune/subgraph engineering that §5 eliminated.

## 11. Tooling

Python: `gudhi` (SimplexTree, persistence), `hypernetx`, `networkx`, `ripser`/`persim` (return-space check), `pandas`, `requests`. Reproducibility: Jupyter + git. Verified working against the live API in the Week-0 run.

## 12. Questions for the faculty mentor

1. LP-token vertices vs. resolved underlying assets (§6.1) — which is the more defensible default, and should both be primary?
2. Is the skeleton-vs-nerve decomposition (§6.3) an adequate formalization of "higher-order structure matters," or is there a better-established statistic?
3. Is the matched placebo-window design (§7) acceptable to an econometrician at N = 1–2 events, and is there a colleague who should look at it?
4. Hofstra resources: WRDS access, compute, undergraduate research funding, symposium deadlines.

## Key references

- Forte, F. D. (2026). *It Takes Two to Tango, but More to Assess Systemic Risk: Credit Networks Through the Lens of Hypergraphs.* arXiv:2607.10943. [Hypergraph centrality on TradFi credit-registry data — evidence higher-order finance is a live area; not a homology or DeFi paper.]
- Gidea, M. & Katz, Y. (2018). Persistent homology of equity-index returns around crashes. [Origin of the return-space TDA line; establishes landscape-norm conventions.]
- Bick, Gross, Harrington, Schaub (2023). *What Are Higher-Order Networks?* SIAM Review. [Canonical survey: hypergraphs vs. simplicial complexes, nerve constructions.]
- DeFiLlama API — https://defillama.com/docs/api; Dune Analytics (future extensions) — https://dune.com.
