# De-censoring the survivorship bias — the v2 result

The paper, and both external AI reviews, treat delisted pools as **unrecoverable** from
DeFiLlama, forcing a survivor-only reconstruction and bounding every claim by a
7.5–12.5% survivorship ceiling. **That premise is false.** The Wayback Machine archived
`yields.llama.fi/pools` roughly weekly from Oct 2022, each snapshot the *full* universe
at that date — dead pools included — with the identical schema. `decensor.py` rebuilds
the complex on the full historical universe; per snapshot it also restricts to pools
that survive to today, so the **survivorship effect is isolated at fixed representation**.

Evidence: a 36-snapshot series, Oct 2022 → May 2025 (`decensor_series.json`,
`figs/decensor.png`), monthly with a weekly cluster around the USDC depeg.

## Three findings, all clean and reproducible

### 1. Survivor reconstruction sees ~1/10 of the loop structure
Essential $B_1$ is **40–58 on the full universe vs 4–23 on survivors** at every date.
The true universe is 3–4× the survivor universe (234–430 vs 63–178 pools; true
survivorship 24–41%, itself far above the paper's 12.5% *upper bound*). The object the
paper analysed was severely impoverished — at the depeg, 208 of 274 pools were invisible
(35% of universe TVL: FRAX-3CRV \$474M, MIM/OUSD/TUSD/LUSD-3CRV, …).

### 2. The paper's RQ1 headline is a survivorship artifact — in BOTH level and trend
The paper claims *a majority (52–77%) of loops are higher-order fills, declining over
2022–23*. De-censored:

- **Level:** the higher-order fraction is **flat at 0.36 ± 0.04 — a minority**, every
  snapshot, for 2.5 years. Not a majority. The real network is majority *pairwise*.
- **Trend:** there is **no decline**. The survivor fraction falls 0.73 → 0.39, but that
  is the survivor sample converging to the truth as survivorship rises:
  **corr(survivor higher-order fraction, survivorship %) = −0.92.** The "declining
  higher-order structure" is manufactured by the changing sample, not by the network.

So the multi-way rhetoric is **less** supported than the paper concluded, not more, and
its temporal story dissolves entirely. This is the strongest single result in the project
because it is a cautionary finding about a *method* — survivor-based registry
reconstruction, used across DeFi network research — not just about this dataset.

### 3. The null survives de-censoring (the reviewers' core critique fails)
Across the depeg at weekly resolution (Feb–Apr 2023, full universe) essential $B_1$ holds
at ~47 and the gap at ~28 — inert, exactly as the survivor view showed. Restoring all 208
dead pools does **not** reveal hidden dynamics: the structure is rigid even when you can
see everyone. This directly refutes "it only looks rigid because you see survivors."

## Corrections to my own earlier read (honesty log)
- The 4-snapshot peek suggested a late-2023 *erosion* of higher-order structure. The full
  36-snapshot series shows **no erosion** — the de-censored fraction is flat. Retracted.
- True survivorship is not one number: it rises 24% → 41% from 2022 to 2025 (mechanical —
  recent pools are more likely to still exist). The paper's "12.5%" was a different, and
  looser, quantity.

## Still open / WIP (for the v2 paper)
- **LP-token representation.** The 2022–23 archive keeps LP tokens as their own vertices
  (FRAX-3CRV = {FRAX, 3CRV}); today's API base-resolves. Within-archive comparisons above
  are clean; cross-era ones need this controlled. Bonus: the archive *naturally realises
  the "LP-token-as-vertex" fork the paper called untestable* — so that fork can now be run
  (`resolve_archive_lp`, to build).
- **A de-censored placebo/event test** at the ~weekly snapshot cadence (coarser than the
  daily survivor series, but on the real universe).
- **Terra** (May 2022) predates the archive and remains non-de-censorable here.

## What this does to the paper (v2 reframing)
- **New centerpiece + method:** web-archive de-censoring of DeFi registry survivorship.
- **RQ1 corrected:** majority→minority, and the decline is shown to be an artifact
  (Fig. `decensor.png`).
- **Null strengthened:** rigidity holds on the full universe through the depeg.
- **Unchanged headline:** still not "topology predicts crashes"; the event-time null is
  simply now robust rather than survivor-limited.

Reproduce: `python decensor.py --build --start 2022-10-01 --end 2025-06-01 --step 30
--dense-start 2023-02-01 --dense-end 2023-04-20 --dense-step 7 && python decensor_fig.py`
