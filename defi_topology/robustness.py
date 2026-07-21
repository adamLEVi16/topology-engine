#!/usr/bin/env python3
"""
Threshold / window / LP-fork robustness sweep.

Shows whether the observables (essB1, gap, tp0) are stable under the pipeline's free
knobs. This is the evidence that the near-static structure is a property of the object
and not an artifact of one (minshare, half-window, lp_mode) choice — the honest core of
the RQ3 answer.

Reuses the cached charts, so run _fetch.py (or pipeline.py once) first.

CLI:
  python robustness.py --event 2023-03-11 --placebo 2022-08-15
"""
import argparse, datetime, itertools, statistics as S

import pipeline as P


def sweep(event_date, placebo_date=None,
          minshares=(1e-4, 1e-5, 1e-6), halves=(30, 45, 60),
          lps=("resolved", "lp_vertex"), metrics=("essB1", "gap", "tp0")):
    uni = P.universe()
    have = P.fetch_charts(uni)
    charts = P.load_charts(have)
    tok = {u["pool"]: u["toks"] for u in have}
    ev = datetime.date.fromisoformat(event_date)
    pb = datetime.date.fromisoformat(placebo_date) if placebo_date else None

    rows = []
    for ms, half, lp in itertools.product(minshares, halves, lps):
        e, edrop = P.window(ev, charts, tok, half, ms, lp)
        rec = {"minshare": ms, "half": half, "lp": lp, "n_event": len(e),
               "dropped": len(edrop)}
        for m in metrics:
            vals = [r[m] for r in e]
            rec[f"ev_{m}"] = (S.mean(vals), S.pstdev(vals) if len(vals) > 1 else 0)
        if pb:
            b, _ = P.window(pb, charts, tok, half, ms, lp)
            for m in metrics:
                vals = [r[m] for r in b]
                rec[f"pb_{m}"] = (S.mean(vals), S.pstdev(vals) if len(vals) > 1 else 0)
        rows.append(rec)
    return rows, metrics


def print_table(rows, metrics, has_placebo):
    hdr = f"{'minshare':>9} {'half':>4} {'lp':>9} {'nEv':>4} {'drop':>4}  "
    hdr += "  ".join(f"ev_{m:>10}" for m in metrics)
    if has_placebo:
        hdr += "   " + "  ".join(f"pb_{m:>10}" for m in metrics)
    print(hdr)
    for r in rows:
        line = f"{r['minshare']:>9.0e} {r['half']:>4} {r['lp']:>9} {r['n_event']:>4} {r['dropped']:>4}  "
        line += "  ".join(f"{r['ev_'+m][0]:6.2f}±{r['ev_'+m][1]:4.2f}" for m in metrics)
        if has_placebo:
            line += "   " + "  ".join(f"{r['pb_'+m][0]:6.2f}±{r['pb_'+m][1]:4.2f}" for m in metrics)
        print(line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", default="2023-03-11")
    ap.add_argument("--placebo", default=None)
    args = ap.parse_args()
    rows, metrics = sweep(args.event, args.placebo)
    print_table(rows, metrics, has_placebo=bool(args.placebo))


if __name__ == "__main__":
    main()
