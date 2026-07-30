#!/usr/bin/env python3
"""
Pairwise (1-skeleton graph) baselines — the "compared to what?" half of RQ3.

The project's claim is relative: "topological observables carry information BEYOND
pairwise graph metrics." That is only testable if the pairwise metrics are computed
through the same windows and put through the same placebo machinery. This module does
that, on exactly the same complex construction (same universe, share filtration, dust
cap, LP fork) — the graph here IS the 1-skeleton of the day's nerve complex.

Per day:
  unweighted skeleton (structure):
    V, E, density, n_comp        — size / fragmentation
    transitivity                 — global clustering (3*triangles / connected triples)
    spec_rad                     — largest adjacency eigenvalue
    deg_cv                       — degree dispersion (centralization proxy)
  share-weighted skeleton (intensity):
    w_spec_rad                   — largest eigenvalue of A_w, A_w[i,j] = sum of shares
                                   of pools containing both i and j. This is the
                                   pairwise object that moves daily, the fair rival
                                   to tp0 (H0 total persistence).

Outputs baseline_long.json over a date range, prints an event-vs-placebo table, and —
the RQ3 punchline — runs the SAME placebo-window permutation test (inference.py) on
every graph metric next to the topological ones from the matching topology series.

Run:
  python baselines.py --start 2022-04-09 --end 2023-12-31 \
      --event 2023-03-11 --placebo 2023-06-15 --topo long_series.json
"""
import argparse, datetime, itertools, json, math, os, statistics as S

import numpy as np

import pipeline as P
from inference import placebo_permutation


# ------------------------------------------------------------------------------------
def day_graph(ds, charts, tok, minshare=P.MINSHARE, lp_mode="resolved"):
    """One day's 1-skeleton graph metrics, or None if no data. Mirrors the pool loop of
    pipeline.build_complex exactly (same threshold, same resolution) so the graph is the
    1-skeleton of the same complex; consistency is asserted in `selfcheck`."""
    live = {pid: charts[pid].get(ds, 0) for pid in charts}
    live = {pid: v for pid, v in live.items() if v > 0}
    total = sum(live.values())
    if total == 0:
        return None
    verts, pairs_w = {}, {}
    for pid, v in live.items():
        share = v / total
        if share < minshare:
            continue
        ts = P.resolve_tokens(tok[pid], lp_mode)
        if len(ts) < 2:
            continue
        ids = []
        for t in ts:
            verts.setdefault(t, len(verts)); ids.append(verts[t])
        for e in itertools.combinations(sorted(ids), 2):
            pairs_w[e] = pairs_w.get(e, 0.0) + share
    V = len(verts)
    E = len(pairs_w)
    if V == 0:
        return None

    A = np.zeros((V, V)); Aw = np.zeros((V, V))
    for (i, j), w in pairs_w.items():
        A[i, j] = A[j, i] = 1.0
        Aw[i, j] = Aw[j, i] = w
    deg = A.sum(axis=1)

    # components (union-find over edges)
    parent = list(range(V))
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for (i, j) in pairs_w:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj
    n_comp = len({find(i) for i in range(V)})

    triangles = np.trace(A @ A @ A) / 6.0
    triples = float((deg * (deg - 1)).sum()) / 2.0
    transitivity = 3.0 * triangles / triples if triples > 0 else 0.0

    spec = float(np.linalg.eigvalsh(A)[-1]) if V > 1 else 0.0
    wspec = float(np.linalg.eigvalsh(Aw)[-1]) if V > 1 else 0.0
    density = 2.0 * E / (V * (V - 1)) if V > 1 else 0.0
    deg_cv = float(deg.std() / deg.mean()) if deg.mean() > 0 else 0.0

    return dict(date=ds, V=V, E=E, density=density, n_comp=n_comp,
                transitivity=transitivity, spec_rad=spec, w_spec_rad=wspec,
                deg_cv=deg_cv)


GRAPH_METRICS = ["E", "density", "n_comp", "transitivity", "spec_rad", "w_spec_rad", "deg_cv"]


def selfcheck(charts, tok, ds):
    """Assert the local edge/vertex construction matches pipeline.build_complex."""
    live = {pid: charts[pid].get(ds, 0) for pid in charts}
    live = {pid: v for pid, v in live.items() if v > 0}
    total = sum(live.values())
    shares = {pid: v / total for pid, v in live.items()}
    st, verts, edges, n_ho, used = P.build_complex(shares, tok, P.MINSHARE, "resolved")
    g = day_graph(ds, charts, tok)
    assert g["V"] == len(verts) and g["E"] == len(edges), \
        f"skeleton mismatch on {ds}: graph V/E {g['V']}/{g['E']} vs complex {len(verts)}/{len(edges)}"
    # B0 must agree with component count
    st.make_filtration_non_decreasing(); st.compute_persistence(persistence_dim_max=True)
    assert g["n_comp"] == st.betti_numbers()[0], f"B0 mismatch on {ds}"


def build_range(charts, tok, start, end, check_every=90):
    """Daily graph metrics over [start, end]. Re-runs the skeleton selfcheck on a
    sampled date every `check_every` appended days, so graph/complex parity is verified
    across the evolving universe, not just at the event date."""
    rows, day = [], datetime.date.fromisoformat(start)
    d1 = datetime.date.fromisoformat(end)
    while day <= d1:
        r = day_graph(day.isoformat(), charts, tok)
        if r:
            rows.append(r)
            if check_every and len(rows) % check_every == 0:
                selfcheck(charts, tok, r["date"])
        day += datetime.timedelta(days=1)
    return rows


def _summ(rows, k):
    """Mean and sd of column k. Returns NaN for the mean on an empty row set rather than
    raising StatisticsError or reporting 0.0, which would look like a measurement."""
    vals = [r[k] for r in rows]
    if not vals:
        return math.nan, 0.0
    return S.mean(vals), (S.pstdev(vals) if len(vals) > 1 else 0.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2022-04-09")
    ap.add_argument("--end", default="2023-12-31")
    ap.add_argument("--event", default="2023-03-11")
    ap.add_argument("--placebo", default="2023-06-15")
    ap.add_argument("--half", type=int, default=30)
    ap.add_argument("--topo", default="long_series.json",
                    help="matching topology series (make_series.py output) for the "
                         "side-by-side RQ3 table; skipped if absent")
    ap.add_argument("--out", default="baseline_long.json")
    args = ap.parse_args()

    uni = P.universe(); have = P.fetch_charts(uni)
    charts = P.load_charts(have); tok = {u["pool"]: u["toks"] for u in have}

    selfcheck(charts, tok, args.event)
    print("selfcheck: 1-skeleton matches pipeline complex (V, E, B0)")

    if os.path.exists(args.out):
        blob = json.load(open(args.out))
        rows = blob["rows"]
        meta = blob.get("meta", {})
        if (meta.get("start"), meta.get("end")) != (args.start, args.end):
            print(f"WARNING: cached {args.out} spans {meta.get('start')}..{meta.get('end')} "
                  f"but --start/--end request {args.start}..{args.end}; delete it to rebuild")
        print(f"loaded {args.out}: {len(rows)} days")
    else:
        rows = build_range(charts, tok, args.start, args.end)
        json.dump({"rows": rows, "meta": vars(args)}, open(args.out, "w"))
        print(f"wrote {args.out}: {len(rows)} days")

    by = {r["date"]: r for r in rows}
    def win(center):
        c = datetime.date.fromisoformat(center)
        return [by[(c + datetime.timedelta(d)).isoformat()] for d in range(-args.half, args.half + 1)
                if (c + datetime.timedelta(d)).isoformat() in by]

    ev, pb = win(args.event), win(args.placebo)
    print(f"\ngraph metrics, event ({args.event}) vs placebo ({args.placebo}):")
    for k in GRAPH_METRICS:
        em, es = _summ(ev, k); pm, ps = _summ(pb, k)
        print(f"    {k:13s} {em:9.3f}±{es:6.3f}   vs   {pm:9.3f}±{ps:6.3f}")

    # --- RQ3 punchline: same placebo permutation for graph AND topology metrics -----
    print(f"\nplacebo-window permutation (event {args.event}, {2*args.half+1}-day windows):")
    print(f"    {'metric':16s} {'kind':9s} {'event_stat':>10} {'pct':>6} {'p':>6}")
    for k in GRAPH_METRICS:
        r = placebo_permutation(rows, args.event, k, args.half)
        print(f"    {k:16s} {'graph':9s} {r['event_stat']:10.3f} {r['event_percentile']:6.1f} "
              f"{r['p_value_two_sided']:6.3f}")
    if os.path.exists(args.topo):
        topo_rows = json.load(open(args.topo))["event"]
        for k in ["essB1", "gap", "tp0", "B0"]:
            r = placebo_permutation(topo_rows, args.event, k, args.half)
            print(f"    {k:16s} {'topology':9s} {r['event_stat']:10.3f} {r['event_percentile']:6.1f} "
                  f"{r['p_value_two_sided']:6.3f}")
    else:
        print(f"    (topology series {args.topo} not found; run make_series.py)")


if __name__ == "__main__":
    main()
