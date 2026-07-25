#!/usr/bin/env python3
"""
De-censored event test, with the reference distribution matched on snapshot spacing.

The v2 manuscript asked "is the pre->post change large relative to the distribution of
all consecutive-snapshot changes?" and reported percentiles from that. Two problems with
running it over the raw pair list:

  1. SPACING. Crawl gaps run 1-83 days (median ~26), but the depeg window is 9 days and
     the Curve window is 3. Drift grows with the gap, so judging a 9-day change against a
     reference set dominated by month-plus intervals makes the event look routine by
     construction -- the test is biased toward the null it reports. We therefore also
     report the percentile against gap-matched pairs only.
  2. TIES. The observables are small integers, so |delta| repeats heavily and the
     percentile depends on whether ties are counted below or at the event value. On the
     depeg that choice alone moves essential B1 from the 23rd to the 49th percentile.
     We use the MID-RANK convention (the midpoint), which is the standard fix and is
     reported alongside the strict/weak bounds so nothing is hidden.

Also reports the DETECTION THRESHOLD: the smallest |delta| that would clear the 95th
percentile of routine drift. That is the number that says what the test could have seen,
as opposed to what it did see.

Run:  python event_test.py            # all four observable x representation cells
      python event_test.py --json out.json
"""
import argparse
import datetime
import glob
import json
import statistics as S

import decensor as D

EVENTS = {
    "USDC depeg":     (datetime.date(2023, 3, 7),  datetime.date(2023, 3, 16)),
    "Curve/Vyper":    (datetime.date(2023, 7, 30), datetime.date(2023, 8, 2)),
}
GAP_MATCH_DAYS = 14          # "comparable interval" band for the short event windows
OBSERVABLES = ("essB1", "gap")
REPRS = (("lp_vertex", False), ("resolved", True))


def crawl_index():
    m = {}
    for fn in sorted(glob.glob("archive/*.json")):
        t = fn.split("/")[-1][:8]
        m[datetime.date(int(t[:4]), int(t[4:6]), int(t[6:8]))] = fn
    return m


def load_uni(fn):
    with open(fn) as fh:
        return [p for p in json.load(fh) if D.is_universe(p)]


def build_series(M, repair=True):
    """Observables per crawl, with the integrity scan + transient-dip repair applied to
    any crawl flagged as corrupted (the 2023-08-02 case). Mirrors the manuscript."""
    dates = sorted(M)
    raw = {d: load_uni(M[d]) for d in dates}
    with_tvl = {}
    for d in dates:
        with open(M[d]) as fh:
            with_tvl[d] = D.universe_tvl(json.load(fh))

    def flagged(i):
        nb = [with_tvl[dates[j]] for j in (i - 1, i + 1) if 0 <= j < len(dates)]
        if not nb:
            return False
        med = sorted(nb)[len(nb) // 2]
        return with_tvl[dates[i]] < 0.6 * med

    out = {}
    for i, d in enumerate(dates):
        uni = raw[d]
        if repair and flagged(i):
            pre = raw[dates[max(i - 1, 0)]]
            post = raw[dates[min(i + 1, len(dates) - 1)]]
            uni, _ = D.repair_transient_dips(uni, pre, post)
        row = {}
        for name, res in REPRS:
            o = D.observables(uni, resolve=res)
            row[name] = {k: o[k] for k in OBSERVABLES} if o else None
        out[d] = row
    return dates, out


def pair_table(dates, series, repr_name, obs):
    """[(gap_days, |delta|, from, to)] over consecutive crawls."""
    rows = []
    for i in range(len(dates) - 1):
        a, b = series[dates[i]][repr_name], series[dates[i + 1]][repr_name]
        if a is None or b is None:
            continue
        rows.append(((dates[i + 1] - dates[i]).days, abs(b[obs] - a[obs]),
                     dates[i], dates[i + 1]))
    return rows


def percentile(ref, value):
    """Strict, weak and mid-rank percentile of `value` within the list `ref`."""
    n = len(ref)
    lo = 100 * sum(1 for x in ref if x < value) / n
    hi = 100 * sum(1 for x in ref if x <= value) / n
    return lo, hi, (lo + hi) / 2


def threshold(ref, q=95):
    """Smallest |delta| clearing the q-th percentile of the reference set."""
    s = sorted(ref)
    return s[min(int(q / 100 * len(s)), len(s) - 1)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="write results here")
    ap.add_argument("--band", type=int, default=GAP_MATCH_DAYS)
    a = ap.parse_args()

    M = crawl_index()
    dates, series = build_series(M)
    print(f"{len(dates)} crawls, {dates[0]} to {dates[-1]}, transient-dip repair applied\n")

    results = []
    for repr_name, _ in REPRS:
        for obs in OBSERVABLES:
            pairs = pair_table(dates, series, repr_name, obs)
            allref = [d for _, d, _, _ in pairs]
            shortref = [d for g, d, _, _ in pairs if g <= a.band]
            print(f"--- {obs}, {repr_name} "
                  f"(reference: {len(allref)} pairs all-gaps, "
                  f"{len(shortref)} pairs <={a.band}d) ---")
            print(f"    routine |delta|  all-gaps: median {S.median(allref):.0f}, "
                  f"mean {S.mean(allref):.2f}, 95th pct {threshold(allref)}")
            print(f"    routine |delta|  <={a.band}d : median {S.median(shortref):.0f}, "
                  f"mean {S.mean(shortref):.2f}, 95th pct {threshold(shortref)}")
            for ev, (d0, d1) in EVENTS.items():
                if d0 not in series or d1 not in series:
                    print(f"    {ev:12s} SKIPPED (crawl missing)")
                    continue
                v0, v1 = series[d0][repr_name], series[d1][repr_name]
                delta = abs(v1[obs] - v0[obs])
                gap = (d1 - d0).days
                _, _, mid_all = percentile(allref, delta)
                lo, hi, mid_short = percentile(shortref, delta)
                print(f"    {ev:12s} gap {gap:2d}d  |delta|={delta:2d}  "
                      f"({v0[obs]} -> {v1[obs]})   "
                      f"mid-rank pct: all-gaps {mid_all:4.0f}th, "
                      f"matched {mid_short:4.0f}th [{lo:.0f}-{hi:.0f}]")
                results.append(dict(observable=obs, representation=repr_name, event=ev,
                                    gap_days=gap, delta=delta,
                                    pre=v0[obs], post=v1[obs],
                                    pct_all_gaps_midrank=round(mid_all, 1),
                                    pct_matched_midrank=round(mid_short, 1),
                                    pct_matched_strict=round(lo, 1),
                                    pct_matched_weak=round(hi, 1),
                                    n_ref_all=len(allref), n_ref_matched=len(shortref),
                                    detect95_all=threshold(allref),
                                    detect95_matched=threshold(shortref)))
            print()

    if a.json:
        with open(a.json, "w") as fh:
            json.dump(results, fh, indent=1)
        print(f"wrote {a.json}")


if __name__ == "__main__":
    main()
