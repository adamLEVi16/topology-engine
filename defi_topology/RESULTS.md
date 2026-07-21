# DeFi Topology MVP — Results So Far

Status: preliminary. One event (USDC depeg, Mar 2023), survivor-only universe, n=1.
Everything below is reproduced by `defi_topology_pipeline.py`; numbers cited are from
the full 602-pool run.

> **NOTE (hardened build):** these are the original v1 findings. Findings 2 and 3 are
> refined/overturned by the hardened pipeline — see `METHODS.md` §2. Keep this file as
> the record of what the first run showed.

## What was built

An end-to-end pipeline that, for any stress-event date:
1. pulls the current Ethereum stablecoin-pool universe from DeFiLlama (free, no auth);
2. reconstructs each pool's daily TVL history (back to ~Feb 2022);
3. builds a daily simplicial complex from pool co-membership under a **TVL-share
   (level-invariant) filtration** — so results are not a laundered copy of the raw
   TVL drawdown baseline;
4. tracks topological observables through a [-30, +30] day window vs a matched calm
   control window.

Ran against the **USDC depeg (2023-03-11)**, control window **2023-01-11**.

## Finding 0 — the historical reconstruction works, but survivorship is severe

Per-pool TVL history reaches back to Feb 2022, so the historical complex is buildable
straight from the free API — **no Dune / subgraph needed for the MVP.** That removes the
project's hardest data-engineering dependency.

But only **75 of 602 (12.5%)** of today's stablecoin pools were live on the depeg date.
The historical complex is therefore reconstructed from a thin survivor slice.
Important honesty note: 12.5% is *"how many current pools are old enough,"* an **upper
bound on usable history** — not true survivorship. The fraction of March-2023 pools that
survived to today is **not recoverable from this API**; delisted pools are gone. Any claim
must be stated as survivor-conditional.

## Finding 1 — persistence landscapes are the wrong summary here (methodological)

Under the share-weighted filtration, **every H1 class is essential** — an
infinite-persistence bar. Loops that form among the strong pools are never closed by
weaker pools. Consequence: persistence landscapes and L^p norms — the standard
Gidea–Katz summary that essentially all TDA-in-finance work runs on — **evaluate to ~0
on this object**, because they discard infinite bars.

This is a genuine, publishable methodological point independent of the contagion
question: the return-space TDA toolkit does not transfer to structural liquidity
complexes. The right observables are **essential Betti numbers** and **H0 total
persistence**, which is what the pipeline tracks.

## Finding 2 — the higher-order (loop) structure barely moves

| observable | event (Mar) | control (Jan) |
|---|---|---|
| essential B1 | 4.75 ± 0.72 | 4.00 ± 0.00 |
| 1-skeleton cycle rank | 16.57 ± 1.03 | 15.00 ± 0.00 |
| higher-order gap (skel − essB1) | 11.82 ± 0.38 | 11.00 ± 0.00 |

Read this carefully. The calm control is **perfectly rigid** (zero variance): in a normal
month the loop structure is a fixed object. The event window shows a **modest lift and
destabilization** — essential B1 rises ~4.0 → ~4.75 and gains day-to-day variance. So the
depeg does perturb the higher-order structure, but the effect is small and the loop
skeleton is largely invariant. This is suggestive, not established (n=1 event, one control,
survivor-censored).

## Finding 3 — the clearer movement is in H0 (connectivity)

H0 total persistence: **2.06 ± 0.21 (event) vs 2.34 ± 0.20 (control)** — components merge
at lower filtration values during stress, i.e. assets that are separable in calm periods
become tightly co-exposed. Economically sensible (flight-to-coordination). **But H0 is
connected components, which the 1-skeleton graph already gives you.** So the cleanest
signal sits in the dimension where topology is *most redundant* with pairwise metrics.

## Honest bottom line (RQ3 so far)

Not null — but leaning against the headline hypothesis. The multi-way loop structure is
nearly static through the largest stablecoin depeg on record; what perturbation exists is
modest and partly in a feature (H0/connectivity) that pairwise graph methods capture
anyway. The strongest results in hand are (a) the methodological finding that landscapes
don't apply, and (b) the survivorship ceiling that bounds any registry-based study.

That is still a real paper — it's just a more measured one than "topology predicts DeFi
crashes."

## Limitations (state these in any writeup)

- Survivorship: 12.5% history ceiling; true dead-fraction unrecoverable from this API.
- n = 1 event, single control window — no cross-event inference is valid yet.
- MINSHARE=1e-5 dust cap and a single share-based filtration; sensitivity untested.
- LP-token resolution fork (keep 3CRV as a vertex vs. resolve to {USDC,USDT,DAI}) not yet
  run — this can materially change the loop structure and must be tested.
- Ethereum-only, stablecoin-flagged pools only.

## Next steps (in priority order)

1. **Terra/UST window** — the decisive test. A slower, deeper structural break than a
   3-day depeg; the most likely place for essential B1 to actually shift. Measure its
   survivorship first (it will be worse). Command:
   `python defi_topology_pipeline.py --event 2022-05-10 --control 2022-03-10 --tag terra`
2. **Second control window** + permutation test over placebo windows, so "event window is
   abnormal" becomes a statement with an effect size and CI rather than an eyeball.
3. **LP-resolution sensitivity** — rerun with 3CRV resolved into its underlying assets;
   report both forks.
4. **Pre-register** the observable set (essB1, gap, tp0) before touching any further event
   windows.
5. Only if 1–4 show signal: consider extending to lending-collateral or liquidation
   generators (needs Dune / subgraph data — the hard part deferred from v1).
