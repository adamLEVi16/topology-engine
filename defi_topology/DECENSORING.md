# De-censoring the survivorship bias (the "fatal flaw" is measurable)

The paper, and both external AI reviews, treat delisted pools as **unrecoverable** from
DeFiLlama, forcing a survivor-only reconstruction and bounding every claim by a
7.5–12.5% survivorship ceiling. **That premise is false.** The Wayback Machine archived
`yields.llama.fi/pools` roughly weekly from Oct 2022, each snapshot being the *full*
universe at that date — dead pools included — with the identical schema. `decensor.py`
uses this to rebuild the complex on the full historical universe.

For each archived snapshot we build the nerve complex two ways, **holding token
representation constant** (both from the same snapshot), so only survivorship varies:

| date | true universe | survivors | true surv. | essB₁ (full / surv) | gap (full / surv) | HO-fraction (full / surv) |
|---|---:|---:|---:|---:|---:|---:|
| 2022-11-10 | 241 | 63 | 26% | **36 / 4** | 24 / 11 | **0.40 / 0.73** |
| 2023-03-07 | 274 | 66 | 24% | **48 / 4** | 28 / 11 | **0.37 / 0.73** |
| 2023-06-06 | 246 | 76 | 31% | **46 / 4** | 31 / 8 | **0.40 / 0.67** |
| 2023-11-28 | 235 | 84 | 36% | **42 / 6** | 18 / 11 | **0.30 / 0.65** |

## What is solid (clean, same-snapshot, reproducible)

1. **Dead pools are recoverable.** The archive holds the full registry; `decensor.py`
   reconstructs it. The "unrecoverable" premise underpinning the whole limitations
   section is wrong.

2. **Survivor reconstruction captured ~10% of the real loop structure.** essB₁ is
   36–48 on the full universe vs **4–6** on survivors, every date. The object the paper
   analysed was severely impoverished — the 208 dead pools at the depeg (35% of universe
   TVL, incl. FRAX-3CRV $474M, MIM-3CRV, OUSD/TUSD/LUSD-3CRV) carried most of the loops.

3. **The RQ1 headline is inverted — and it was a survivorship artifact.** The paper
   claims *a majority (52–77%) of loops are higher-order fills*. The survivor-subset here
   reproduces that (0.65–0.73), **but the de-censored fraction is 0.30–0.40 — a
   minority.** Survivors are disproportionately the big multi-asset pools (3pool + wrapped
   copies), which inflates the higher-order share; the many dead *pairwise* metapool
   edges (FRAX–3CRV, etc.) make the true structure majority-pairwise. **Corrected finding:
   most of the loop structure is pairwise — the multi-way rhetoric is *less* supported
   than the paper concluded, not more.**

4. **The null survives de-censoring.** Across the immediate depeg (2023-03-07 → 2023-03-12,
   both full universes) essB₁ 48→50 and gap 28→28 — inert, exactly as the survivor view
   showed. This **directly refutes the reviewers' central criticism** ("it only looks
   rigid because you see survivors"): restore the dead pools and it is still rigid at the
   event timescale.

## What is preliminary (needs a proper snapshot series before it goes in the paper)

- **A longer-arc erosion of higher-order structure** is suggested (gap 28→18, HO-fraction
  0.40→0.30, ho-pools 33→22 from mid-2023 to late-2023) but rests on four noisy weekly
  snapshots. Indicative, not established.
- Snapshots are ~weekly crawl dates, not daily, so the daily [−30,+30] placebo permutation
  cannot yet be run on de-censored data.
- **Representation across eras:** the 2022–23 archive keeps LP tokens as their own
  vertices (FRAX-3CRV = {FRAX, 3CRV}); today's API base-resolves them. The de-censored
  vs survivor comparison above is clean (one snapshot, one representation), but comparing
  de-censored history to today needs this controlled. This also means the archive
  *naturally realises the "LP-token-as-vertex" fork the paper called untestable* —
  another claim to revisit.
- Terra (May 2022) predates the earliest snapshot (Oct 2022) and is not de-censorable
  here.

## What this does to the paper

- **Corrects** RQ1 (majority → minority higher-order) and shows the original number was a
  survivorship artifact.
- **Strengthens** the null: rigidity holds on the de-censored universe at the event.
- **Adds a genuinely novel method** — web-archive de-censoring of DeFi registry
  survivorship — that applies to *any* registry-based DeFi network study, not just this
  one. This is the most transferable contribution in the project.
- **Does not** overturn the headline: this is still not "topology predicts crashes." The
  event-time null is now stronger, and the descriptive story is corrected and cleaner.

Reproduce: `python decensor.py --series 2022-11-10 2023-03-07 2023-06-06 2023-11-28`
