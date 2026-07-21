#!/usr/bin/env python3
"""
Build ONE long continuous daily series of observables over a date range, so the
placebo-window permutation test (inference.py) has a real baseline to slide across.
Reuses the cached charts. Writes {"event": [...], "meta": {...}} so inference.py can
load it directly.

  python make_series.py --start 2022-06-01 --end 2023-12-31 --lp resolved --out long_series.json
"""
import argparse, datetime, json
import pipeline as P


def build_range(start, end, minshare=P.MINSHARE, lp_mode="resolved", fill=True):
    uni = P.universe()
    have = P.fetch_charts(uni)
    charts = P.load_charts(have, fill=fill)
    tok = {u["pool"]: u["toks"] for u in have}
    d0 = datetime.date.fromisoformat(start)
    d1 = datetime.date.fromisoformat(end)
    rows, day = [], d0
    while day <= d1:
        r = P.day_metrics(day.isoformat(), charts, tok, minshare, lp_mode)
        if r:
            rows.append(r)
        day += datetime.timedelta(days=1)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2022-06-01")
    ap.add_argument("--end", default="2023-12-31")
    ap.add_argument("--minshare", type=float, default=P.MINSHARE)
    ap.add_argument("--lp", choices=["resolved", "lp_vertex"], default="resolved")
    ap.add_argument("--out", default="long_series.json")
    args = ap.parse_args()
    rows = build_range(args.start, args.end, args.minshare, args.lp)
    json.dump({"event": rows, "meta": {"start": args.start, "end": args.end,
                                       "lp_mode": args.lp, "minshare": args.minshare}},
              open(args.out, "w"))
    print(f"wrote {args.out}: {len(rows)} daily rows ({rows[0]['date']} .. {rows[-1]['date']})")


if __name__ == "__main__":
    main()
