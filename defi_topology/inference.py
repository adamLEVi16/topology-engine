#!/usr/bin/env python3
"""
Non-parametric inference for the DeFi-topology event study.

Two tools, both chosen for a near-static, piecewise-constant series with a handful of
distinct topological states and only N=1 event (so no cross-event or parametric
machinery is valid):

  1. placebo_permutation — the honest replacement for the v1 "matched control". Instead
     of comparing the event window to the ADJACENT pre-event window (which is the same
     continuous series and shares dates), slide the [-half,+half] window across every
     admissible center date in a long baseline and ask where the event window's statistic
     falls in that placebo distribution. Reports a two-sided empirical p-value and the
     event's percentile. Honest about its own limit: if the series has K distinct states,
     the placebo distribution has at most ~K distinct values and the smallest achievable
     p-value is bounded below by 1/(#placebos).

  2. block_bootstrap_ci — circular moving-block bootstrap CI for a window statistic,
     with the block length chosen to respect the run-length autocorrelation of a
     piecewise-constant series (a single pool crossing threshold moves the whole level).

Runs on any series produced by pipeline.py (or the original *_series.json). No network.

CLI:
  python inference.py usdc_depeg_series.json --event 2023-03-11 --metric essB1 --half 30
"""
import argparse, datetime, json, math, random, statistics as S


# ------------------------------------------------------------------------------------
def _index_by_date(series):
    """series: list of daily dicts (any of pipeline.py's `event`/`placebo`, or the
    original event+control concatenated). Returns {date(): row} de-duplicated."""
    out = {}
    for r in series:
        out[datetime.date.fromisoformat(r["date"])] = r
    return out


def _window_rows(by_date, center, half, full=True):
    """Contiguous rows in [center-half, center+half]. With full=True (the default, used
    for both the event window and every placebo) all 2*half+1 days must be present, so
    truncated series-edge windows never enter the reference distribution; full=False
    tolerates gaps down to `half` present days."""
    days = [center + datetime.timedelta(d) for d in range(-half, half + 1)]
    rows = [by_date[d] for d in days if d in by_date]
    need = 2 * half + 1 if full else half
    return rows if len(rows) >= need else None


def placebo_permutation(series, event_date, metric, half=30, stat="mean"):
    """Empirical placebo test. `series` should be as LONG a continuous daily run as you
    have (concatenate every calm span you trust). Every window (event and placebo) must
    be full-length, and placebo windows share NO days with the event window (centers
    within 2*half of the event are excluded). Placebos still overlap each other — see
    n_disjoint_equivalent in the result for the effective-sample honesty diagnostic.
    Returns dict with the event statistic, the placebo distribution summary, percentile,
    and two-sided empirical p-value."""
    by_date = _index_by_date(series)
    ev = datetime.date.fromisoformat(event_date)
    agg = {"mean": S.mean, "max": max, "min": min,
           "range": lambda xs: max(xs) - min(xs),
           "sd": lambda xs: S.pstdev(xs) if len(xs) > 1 else 0.0}[stat]

    def wstat(center):
        rows = _window_rows(by_date, center, half)
        return None if rows is None else agg([r[metric] for r in rows])

    ev_stat = wstat(ev)
    if ev_stat is None:
        raise ValueError("event window has insufficient coverage in this series")

    all_days = sorted(by_date)
    placebos = []
    for c in all_days:
        # Windows [c-half, c+half] and [ev-half, ev+half] share days iff
        # |c-ev| <= 2*half. Placebos that overlap the event window are dragged toward
        # the event statistic and pad the middle of the reference distribution —
        # biasing TOWARD a null verdict — so they are excluded entirely.
        if abs((c - ev).days) <= 2 * half:
            continue
        s = wstat(c)
        if s is not None:
            placebos.append(s)
    if not placebos:
        raise ValueError("no admissible event-disjoint placebo windows in this series")

    ge = sum(1 for s in placebos if s >= ev_stat)
    le = sum(1 for s in placebos if s <= ev_stat)
    n = len(placebos)
    p_two = min(1.0, 2 * min(ge, le) / n)
    pct = 100.0 * sum(1 for s in placebos if s < ev_stat) / n
    # Placebo windows are event-disjoint but overlap EACH OTHER (they slide by one
    # day), so they are autocorrelated: n overstates the information content. The
    # disjoint-equivalent count is the honest effective-sample diagnostic.
    return dict(metric=metric, stat=stat, half=half, event_stat=ev_stat,
                n_placebos=n, n_disjoint_equivalent=n // (2 * half + 1),
                placebo_mean=S.mean(placebos),
                placebo_sd=S.pstdev(placebos) if n > 1 else 0.0,
                placebo_min=min(placebos), placebo_max=max(placebos),
                distinct_placebo_values=len(set(round(s, 6) for s in placebos)),
                event_percentile=pct, p_value_two_sided=p_two,
                p_value_floor=1.0 / n)


def block_bootstrap_ci(values, stat="mean", block=7, n_boot=5000, alpha=0.05, seed=0):
    """Circular moving-block bootstrap CI for a window statistic. `block` should be >=
    the typical run length of the series (piecewise-constant => long runs => larger
    block). Returns (point, lo, hi)."""
    rng = random.Random(seed)
    m = len(values)
    if m == 0:
        return (float("nan"),) * 3
    agg = {"mean": S.mean, "max": max, "min": min,
           "sd": lambda xs: S.pstdev(xs) if len(xs) > 1 else 0.0}[stat]
    point = agg(values)
    block = max(1, min(block, m))
    boots = []
    for _ in range(n_boot):
        sample = []
        while len(sample) < m:
            start = rng.randrange(m)
            sample.extend(values[(start + j) % m] for j in range(block))
        boots.append(agg(sample[:m]))
    boots.sort()
    lo = boots[int((alpha / 2) * n_boot)]
    hi = boots[int((1 - alpha / 2) * n_boot) - 1]
    return point, lo, hi


def longest_run(values):
    """Diagnostic: length of the longest constant run — informs the bootstrap block size
    and honestly bounds how much any test can resolve."""
    if not values:
        return 0
    best = cur = 1
    for a, b in zip(values, values[1:]):
        cur = cur + 1 if a == b else 1
        best = max(best, cur)
    return best


# ------------------------------------------------------------------------------------
def _load_series(path):
    """Load a series JSON and return one long continuous daily list. Handles both the
    hardened schema ({event, placebo, ...}) and the original ({event, control, ...})."""
    d = json.load(open(path))
    rows = {}
    for key in ("event", "placebo", "control"):
        for r in d.get(key, []) or []:
            rows[r["date"]] = r
    return [rows[k] for k in sorted(rows)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("series", help="*_series.json from pipeline.py (or original)")
    ap.add_argument("--event", required=True)
    ap.add_argument("--metric", default="essB1")
    ap.add_argument("--half", type=int, default=30)
    ap.add_argument("--stat", default="mean", choices=["mean", "max", "min", "range", "sd"])
    ap.add_argument("--block", type=int, default=7)
    args = ap.parse_args()

    series = _load_series(args.series)
    print(f"series: {len(series)} distinct daily rows "
          f"({series[0]['date']} .. {series[-1]['date']})")

    by_date = _index_by_date(series)
    ev = datetime.date.fromisoformat(args.event)
    ev_rows = _window_rows(by_date, ev, args.half)
    ev_vals = [r[args.metric] for r in ev_rows] if ev_rows else []
    print(f"metric={args.metric}  distinct states in series="
          f"{len(set(r[args.metric] for r in series))}  "
          f"longest constant run={longest_run([r[args.metric] for r in series])}")

    try:
        res = placebo_permutation(series, args.event, args.metric, args.half, args.stat)
        print("\n--- placebo-window permutation test ---")
        for k in ("event_stat", "placebo_mean", "placebo_sd", "placebo_min", "placebo_max",
                  "n_placebos", "n_disjoint_equivalent", "distinct_placebo_values",
                  "event_percentile", "p_value_two_sided", "p_value_floor"):
            print(f"  {k:24s} {res[k]}")
    except ValueError as e:
        print(f"\nplacebo test not runnable on this series: {e}")

    if ev_vals:
        pt, lo, hi = block_bootstrap_ci(ev_vals, args.stat, args.block)
        print(f"\n--- block bootstrap ({args.stat}, block={args.block}) ---")
        print(f"  event window {args.stat}({args.metric}) = {pt:.4f}   95% CI [{lo:.4f}, {hi:.4f}]")


if __name__ == "__main__":
    main()
