#!/usr/bin/env python3
"""
How large a shock would the event test have needed in order to see it?

The de-censored event test reports that neither the USDC depeg nor the Curve/Vyper
exploit moves the reconstructed structure past routine between-snapshot drift. On its own
that is an absence of evidence: with an integer observable and weekly-to-monthly crawls,
"the structure did not move" and "this test cannot resolve a move this small" produce the
same output. This script separates them.

Method: take a real snapshot, damage it synthetically at increasing severity, and record
where essential B1 leaves the band of routine drift. Three damage models, because they
answer different questions:

  TOP-N      delete the N largest pools by TVL          -- a targeted failure of the
                                                           biggest venues
  TVL-SHARE  delete largest-first until X% of universe  -- a drawdown of stated size
             TVL is gone
  RANDOM     delete a random pool set totalling X% of   -- the same drawdown spread
             TVL, averaged over seeds                      diffusely rather than aimed

The detection thresholds come from event_test.py: the smallest |delta| clearing the 95th
percentile of routine drift, measured against gap-matched intervals (5 loops) and against
all intervals (8 loops) for essential B1 under lp_vertex.

Run:  python injection.py
      python injection.py --date 2023-03-07 --json injection.json
"""
import argparse
import datetime
import glob
import json
import random
import statistics as S

import decensor as D

DETECT_MATCHED = 5     # 95th pct of routine |delta|, gap-matched  (event_test.py)
DETECT_ALLGAPS = 8     # 95th pct of routine |delta|, all gaps


def crawl_index():
    m = {}
    for fn in sorted(glob.glob("archive/*.json")):
        t = fn.split("/")[-1][:8]
        m[datetime.date(int(t[:4]), int(t[4:6]), int(t[6:8]))] = fn
    return m


def load_uni(fn):
    with open(fn) as fh:
        return [p for p in json.load(fh) if D.is_universe(p)]


def tvl(p):
    return p.get("tvlUsd") or 0


def essb1(pools, resolve=False):
    o = D.observables(pools, resolve=resolve)
    return o["essB1"] if o else None


def drop_top_n(pools, n):
    order = sorted(pools, key=lambda p: -tvl(p))
    return order[n:]


def drop_share_largest(pools, share):
    """Delete largest-first until `share` of universe TVL is gone."""
    total = sum(tvl(p) for p in pools)
    order = sorted(pools, key=lambda p: -tvl(p))
    gone, keep = 0.0, []
    for p in order:
        if gone < share * total:
            gone += tvl(p)
        else:
            keep.append(p)
    return keep, gone / total if total else 0.0


def drop_share_random(pools, share, rng):
    total = sum(tvl(p) for p in pools)
    order = pools[:]
    rng.shuffle(order)
    gone, keep = 0.0, []
    for p in order:
        if gone < share * total:
            gone += tvl(p)
        else:
            keep.append(p)
    return keep, gone / total if total else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2023-03-07",
                    help="crawl to damage (default: the depeg pre-event crawl)")
    ap.add_argument("--seeds", type=int, default=12)
    ap.add_argument("--json")
    a = ap.parse_args()

    M = crawl_index()
    d = datetime.date.fromisoformat(a.date)
    if d not in M:
        raise SystemExit(f"no crawl at {d}; have {min(M)} .. {max(M)}")
    pools = load_uni(M[d])
    total = sum(tvl(p) for p in pools)
    base = essb1(pools)
    multi = sum(1 for p in pools if len(D.toks(p)) >= 3)
    print(f"base snapshot {d}: {len(pools)} pools ({multi} multi-asset), "
          f"universe TVL ${total/1e9:.2f}B, essential B1 = {base}")
    print(f"detection thresholds: |delta| >= {DETECT_MATCHED} (gap-matched), "
          f">= {DETECT_ALLGAPS} (all gaps)\n")

    out = {"date": str(d), "base_essB1": base, "pools": len(pools),
           "universe_tvl": total, "top_n": [], "share_largest": [], "share_random": []}

    print("TOP-N  delete the N largest pools by TVL")
    print(f"    {'N':>3} {'TVL removed':>12} {'essB1':>6} {'|delta|':>8}  detected?")
    for n in (1, 2, 3, 5, 8, 12, 16, 24, 32, 48, 64):
        if n >= len(pools):
            break
        kept = drop_top_n(pools, n)
        removed = 1 - sum(tvl(p) for p in kept) / total
        e = essb1(kept)
        dl = abs(e - base)
        flag = "YES" if dl >= DETECT_MATCHED else "no"
        print(f"    {n:3d} {100*removed:11.1f}% {e:6d} {dl:8d}  {flag}")
        out["top_n"].append(dict(n=n, tvl_removed=round(removed, 4), essB1=e, delta=dl))

    print("\nTVL-SHARE  delete largest-first until X% of universe TVL is gone")
    print(f"    {'target':>7} {'actual':>8} {'pools cut':>10} {'essB1':>6} {'|delta|':>8}  detected?")
    for share in (0.05, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70):
        kept, actual = drop_share_largest(pools, share)
        e = essb1(kept)
        dl = abs(e - base)
        flag = "YES" if dl >= DETECT_MATCHED else "no"
        print(f"    {100*share:6.0f}% {100*actual:7.1f}% {len(pools)-len(kept):10d} "
              f"{e:6d} {dl:8d}  {flag}")
        out["share_largest"].append(dict(target=share, actual=round(actual, 4),
                                         pools_cut=len(pools) - len(kept),
                                         essB1=e, delta=dl))

    print(f"\nRANDOM  same TVL share, randomly chosen, mean over {a.seeds} seeds")
    print(f"    {'target':>7} {'pools cut':>10} {'mean essB1':>11} {'mean |delta|':>13}  detected?")
    for share in (0.05, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70):
        es, cuts = [], []
        for s in range(a.seeds):
            kept, _ = drop_share_random(pools, share, random.Random(s))
            e = essb1(kept)
            if e is not None:
                es.append(e)
                cuts.append(len(pools) - len(kept))
        md = S.mean(abs(e - base) for e in es)
        flag = "YES" if md >= DETECT_MATCHED else "no"
        print(f"    {100*share:6.0f}% {S.mean(cuts):10.0f} {S.mean(es):11.1f} "
              f"{md:13.1f}  {flag}")
        out["share_random"].append(dict(target=share, pools_cut=round(S.mean(cuts), 1),
                                        essB1_mean=round(S.mean(es), 2),
                                        delta_mean=round(md, 2),
                                        delta_sd=round(S.pstdev([abs(e-base) for e in es]), 2)))

    # the headline sentence
    def first_hit(rows, key, thr):
        for r in rows:
            if (r["delta"] if "delta" in r else r["delta_mean"]) >= thr:
                return r[key]
        return None
    n_hit = first_hit(out["top_n"], "n", DETECT_MATCHED)
    s_hit = first_hit(out["share_largest"], "actual", DETECT_MATCHED)
    r_hit = first_hit(out["share_random"], "target", DETECT_MATCHED)
    print("\n--- bound on the null ---")
    print(f"  targeted:  deleting the top {n_hit} pools by TVL is the smallest tested "
          f"shock that registers" if n_hit else "  targeted: no tested shock registers")
    print(f"  drawdown:  {100*s_hit:.0f}% of universe TVL, largest-first"
          if s_hit else "  drawdown: no tested share registers")
    print(f"  diffuse :  {100*r_hit:.0f}% of universe TVL at random"
          if r_hit else "  diffuse : no tested share registers")

    if a.json:
        with open(a.json, "w") as fh:
            json.dump(out, fh, indent=1)
        print(f"\nwrote {a.json}")


if __name__ == "__main__":
    main()
