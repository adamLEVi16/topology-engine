# De-censoring the survivorship bias — the v2 result

The paper, and both external AI reviews, treat delisted pools as **unrecoverable** from
DeFiLlama, forcing a survivor-only reconstruction. **That premise is false.** The Wayback
Machine archived `yields.llama.fi/pools` ~weekly from Oct 2022, each snapshot the *full*
universe at that date — dead pools included — with the identical schema. `decensor.py`
rebuilds the complex on the full historical universe (36 snapshots, Oct 2022 → May 2025:
`decensor_series.json`, `figs/decensor.png`).

Because the 2022–23 archive keeps LP tokens as their own vertices (FRAX-3CRV = {FRAX,
3CRV}) while today's API base-resolves them, we can also finally run the **LP-resolution
fork** the paper called "untestable" (68 3CRV-metapools exist in the archive; 0 survive
to today). Combining the two axes gives a clean 2×2 — and it corrects an over-claim from
the first de-censoring pass.

## Finding 1 — survivor reconstruction sees ~1/10 of the loops (solid)
At fixed representation (lp_vertex), essential $B_1$ is **40–58 on the full universe vs
4–23 on survivors**, every date. The true universe is 3–4× the survivor universe (234–430
vs 63–178 pools; true survivorship 24–41%, itself well above the paper's 12.5% *upper
bound*). At the depeg, 208 of 274 pools were invisible — 35% of universe TVL (FRAX-3CRV
\$474M, MIM/OUSD/TUSD/LUSD-3CRV, …).

## Finding 2 — the higher-order *fraction* has no convention-free value
The paper reports *a majority (52–77%) of loops are higher-order, declining over 2022–23*.
That number is fragile to **two** defensible modeling choices that together swing it from
**0.31 to 0.93**. HOfrac [essB₁] by snapshot × representation × sample:

| date | lp_vertex full | lp_vertex surv | resolved full | resolved surv |
|---|---|---|---|---|
| 2022-10 | 0.31 [40] | 0.73 [4] | 0.80 [21] | 0.93 [2] |
| 2023-03 | 0.37 [48] | 0.73 [4] | 0.75 [32] | 0.93 [2] |
| 2023-06 | 0.40 [46] | 0.67 [4] | 0.68 [32] | 0.92 [2] |
| 2023-11 | 0.30 [42] | 0.65 [6] | 0.66 [28] | 0.87 [4] |
| 2024-05 | 0.32 [50] | 0.52 [10] | 0.54 [42] | 0.77 [8] |
| 2024-12 | 0.39 [51] | 0.48 [15] | 0.54 [44] | 0.68 [13] |
| 2025-05 | 0.40 [58] | 0.39 [23] | 0.50 [54] | 0.60 [21] |

- **LP-token representation is the larger driver (~2×).** Resolving 3CRV into
  {DAI,USDC,USDT} collapses the ~68 metapools onto a shared base triangle (a partial
  cone), mechanically inflating the higher-order fraction; keeping 3CRV as a vertex (the
  composability view) does not. Across 36 snapshots, resolving removes ~28% of loops
  (essB₁ 46.8→33.8) yet nearly *doubles* HOfrac (0.36→0.67).
- **Survivorship is a secondary amplifier**, same direction: survivors are the big
  multi-asset pools. Holding representation = resolved (the paper's convention),
  full→survivor pushes 0.75→0.93 at the depeg.
- **Even the trend is convention-dependent.** Under resolved, the de-censored fraction
  genuinely *declines* 0.80→0.50 as metapools die; under lp_vertex it is *flat* ~0.36
  (sd 0.04). Opposite qualitative stories from one dataset. (The *survivor* fraction
  declines under both, corr(survivor HOfrac, survivorship%) ≈ −0.92 for lp_vertex — the
  survivor sample converging to the full-universe value as survivorship rises.)

**Honest RQ1 result: a sensitivity range, not a point.** The paper's "majority, declining"
sits at the high-inflation corner (resolved + survivor); the de-censored, composability-
preserving corner is a flat minority (~0.35). Neither convention is uniquely correct
(resolving = economic exposure to base assets; lp_vertex = composability structure). The
headline number is an artifact of two arbitrary choices — a stronger, and more precisely
decomposed, cautionary finding than survivorship alone.

## Finding 3 — the null is the robust part (confirmed across conventions)
De-censored event test at weekly resolution (Feb–Apr 2023, full universe): the pre→post
depeg change (2023-03-07 → 03-16) is *smaller than typical between-snapshot variation* for
every observable, under **both** representations —

| observable | pre→post Δ | percentile of \|consecutive-snapshot Δ\| | verdict |
|---|---|---|---|
| essB₁ lp_vertex | 1 | 23rd | inert |
| gap lp_vertex | 1 | 14th | inert |
| essB₁ resolved | 0 | 0th | inert |
| gap resolved | 1 | 17th | inert |

So the structural change across the largest stablecoin depeg on record is *less* than the
routine month-to-month drift, on the full de-censored universe, under both LP conventions.
**Unlike the descriptive fraction (Finding 2), the null is robust to every modeling choice
we can vary** — survivorship, LP representation, and cadence. This is the paper's one
convention-independent structural result, and it directly refutes the reviewers' "it only
looks rigid because you see survivors."

## Honesty log (corrections to my own earlier reads)
- **Over-attribution, now fixed:** the previous commit called the RQ1 majority→minority
  flip a *survivorship* artifact. The 2×2 shows **LP-token representation is the larger
  driver**; survivorship is secondary. Corrected above.
- The 4-snapshot peek suggested a late-2023 *erosion* under lp_vertex. The full series
  shows lp_vertex is **flat** (no erosion); the genuine decline lives in the *resolved*
  representation. Clarified.

## What this does to the paper (v2)
- **New centerpiece + method:** web-archive de-censoring of DeFi registry survivorship,
  and — via the archive's native LP-as-vertex representation — the first empirical run of
  the LP-resolution fork.
- **RQ1 reframed:** from "a majority, declining" to "no convention-free value; swings
  0.31–0.93 across survivorship × representation." A sensitivity result, with the two
  drivers decomposed.
- **Null strengthened and elevated to the paper's one robust structural claim:** inert
  through the depeg across sample and (task 9) representation.
- **Unchanged headline:** still not "topology predicts crashes."

Reproduce: `python decensor.py --build ...` then the 2×2 sweep over `archive/`
(`observables(..., resolve=True/False)`).
