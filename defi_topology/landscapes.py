#!/usr/bin/env python3
"""
Verify the linchpin methodological claim (RESULTS.md finding 1 / METHODS.md §4.1):

    "Under the share-weighted filtration every H1 class is essential (an
     infinite-persistence bar), so persistence landscapes / L^p norms — the
     standard Gidea-Katz summary — evaluate to ~0 on this object."

This script computes, for every day in an event window and a placebo window:
  - the H1 persistence diagram, split into finite vs infinite bars;
  - persistence-landscape norms of H1 under the two conventions in use in the
    TDA-finance literature:
      (a) DISCARD    — infinite bars dropped (gudhi / persim default). The claim
                       predicts norms ~ 0 here.
      (b) TRUNCATE   — infinite bars capped at a cutoff T. Norms are then nonzero
                       BUT scale mechanically with the arbitrary cutoff; we show
                       this by reporting two cutoffs (T = max entry filtration of
                       the day's complex, and T = -log10(MINSHARE)).
  - the same for H0 as a contrast (H0 has genuine finite bars, so the landscape
    machinery works there — the failure is specific to H1 on this object).

Landscapes are computed exactly (no sklearn): lambda_k(t) is the k-th largest of
tent(b,d)(t) = max(0, min(t-b, d-t)); norms are numerically integrated on a grid.

Run:  python landscapes.py --event 2023-03-11 --placebo 2023-06-15 --half 30
Writes landscape_audit.json and prints a summary table.
"""
import argparse, datetime, json, math
import pipeline as P

GRID_N = 2000


def tent(b, d, t):
    return max(0.0, min(t - b, d - t))


def landscape_norms(bars, lo, hi, k_max=3):
    """Exact-on-grid L1/L2/Linf of the first k landscapes for finite bars."""
    if not bars or hi <= lo:
        return {"L1": 0.0, "L2": 0.0, "Linf": 0.0}
    dt = (hi - lo) / GRID_N
    l1 = l2 = linf = 0.0
    for i in range(GRID_N + 1):
        t = lo + i * dt
        vals = sorted((tent(b, d, t) for b, d in bars), reverse=True)[:k_max]
        v1 = vals[0] if vals else 0.0
        l1 += v1 * dt
        l2 += v1 * v1 * dt
        linf = max(linf, v1)
    return {"L1": l1, "L2": math.sqrt(l2), "Linf": linf}


def day_diagram(ds, charts, tok, minshare, lp_mode="resolved"):
    live = {pid: charts[pid].get(ds, 0) for pid in charts}
    live = {pid: v for pid, v in live.items() if v > 0}
    total = sum(live.values())
    if total == 0:
        return None
    shares = {pid: v / total for pid, v in live.items()}
    st, verts, edges, n_ho, used = P.build_complex(shares, tok, minshare, lp_mode)
    st.make_filtration_non_decreasing()
    st.compute_persistence(persistence_dim_max=True)
    pers = st.persistence()
    h1 = [(b, d) for (dim, (b, d)) in pers if dim == 1]
    h0 = [(b, d) for (dim, (b, d)) in pers if dim == 0]
    fmax = max((st.filtration(s) for s, _ in zip((s for s, f in st.get_simplices()), range(10**9))), default=0)
    # max filtration actually present (entry value of the weakest simplex)
    fmax = max((f for _, f in st.get_simplices()), default=0.0)
    return h1, h0, fmax


def audit_window(center, charts, tok, half, minshare):
    rows = []
    for dd in range(-half, half + 1):
        ds = (center + datetime.timedelta(dd)).isoformat()
        r = day_diagram(ds, charts, tok, minshare)
        if r is None:
            continue
        h1, h0, fmax = r
        h1_fin = [(b, d) for b, d in h1 if d != float("inf")]
        h1_inf = [(b, d) for b, d in h1 if d == float("inf")]
        h0_fin = [(b, d) for b, d in h0 if d != float("inf")]
        T_hard = -math.log10(minshare)          # filtration ceiling implied by the dust cap
        lo, hi = 0.0, max(fmax, T_hard)
        rows.append({
            "date": ds,
            "h1_total": len(h1), "h1_finite": len(h1_fin), "h1_infinite": len(h1_inf),
            "h1_finite_pers": [round(d - b, 6) for b, d in h1_fin],
            # (a) standard discard convention
            "h1_discard": landscape_norms(h1_fin, lo, hi),
            # (b) truncation conventions
            "h1_trunc_fmax": landscape_norms(
                [(b, d if d != float("inf") else fmax) for b, d in h1], lo, hi),
            "h1_trunc_cap": landscape_norms(
                [(b, d if d != float("inf") else T_hard) for b, d in h1], lo, hi),
            "h0_discard": landscape_norms(h0_fin, lo, hi),
            "fmax": fmax,
        })
    return rows


def summarize(name, rows):
    n = len(rows)
    fin_days = sum(1 for r in rows if r["h1_finite"] > 0)
    fin_total = sum(r["h1_finite"] for r in rows)
    inf_mean = sum(r["h1_infinite"] for r in rows) / n
    mx = lambda key, nrm: max(r[key][nrm] for r in rows)
    mean = lambda key, nrm: sum(r[key][nrm] for r in rows) / n
    print(f"\n== {name}  ({n} days) ==")
    print(f"  H1 bars: mean {sum(r['h1_total'] for r in rows)/n:.2f}/day  "
          f"infinite {inf_mean:.2f}/day  finite TOTAL across window: {fin_total} "
          f"(on {fin_days}/{n} days)")
    if fin_total:
        allp = [p for r in rows for p in r["h1_finite_pers"]]
        print(f"  finite H1 persistences: min {min(allp):.4f}  max {max(allp):.4f}")
    print(f"  H1 landscape (DISCARD):    L2 mean {mean('h1_discard','L2'):.5f}  max {mx('h1_discard','L2'):.5f}   "
          f"Linf max {mx('h1_discard','Linf'):.5f}")
    print(f"  H1 landscape (TRUNC@fmax): L2 mean {mean('h1_trunc_fmax','L2'):.5f}  max {mx('h1_trunc_fmax','L2'):.5f}")
    print(f"  H1 landscape (TRUNC@cap):  L2 mean {mean('h1_trunc_cap','L2'):.5f}  max {mx('h1_trunc_cap','L2'):.5f}")
    print(f"  H0 landscape (DISCARD):    L2 mean {mean('h0_discard','L2'):.5f}  max {mx('h0_discard','L2'):.5f}"
          f"   <- contrast: machinery works where finite bars exist")
    return {"days": n, "h1_finite_total": fin_total, "h1_finite_days": fin_days,
            "h1_discard_L2_max": mx("h1_discard", "L2"),
            "h1_trunc_fmax_L2_mean": mean("h1_trunc_fmax", "L2"),
            "h1_trunc_cap_L2_mean": mean("h1_trunc_cap", "L2"),
            "h0_discard_L2_mean": mean("h0_discard", "L2")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", default="2023-03-11")
    ap.add_argument("--placebo", default="2023-06-15")
    ap.add_argument("--half", type=int, default=30)
    ap.add_argument("--minshare", type=float, default=P.MINSHARE)
    args = ap.parse_args()

    uni = P.universe(); have = P.fetch_charts(uni)
    charts = P.load_charts(have); tok = {u["pool"]: u["toks"] for u in have}

    out = {}
    for name, date in (("event", args.event), ("placebo", args.placebo)):
        rows = audit_window(datetime.date.fromisoformat(date), charts, tok,
                            args.half, args.minshare)
        out[name] = {"center": date, "rows": rows, "summary": summarize(name, rows)}

    json.dump(out, open("landscape_audit.json", "w"))
    print("\nwrote landscape_audit.json")


if __name__ == "__main__":
    main()
