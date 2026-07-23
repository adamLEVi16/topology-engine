#!/usr/bin/env python3
"""
De-censoring DeFi survivorship bias via the Internet Archive.

The whole paper (and both AI reviews) assumed pools delisted before today are
UNRECOVERABLE from DeFiLlama, forcing a survivor-only reconstruction. That assumption
is false: the Wayback Machine archived the registry endpoint (yields.llama.fi/pools)
roughly weekly from Oct 2022 on, and each snapshot is the FULL universe at that date —
including pools that later died — with the same schema (underlyingTokens, tvlUsd,
stablecoin, chain).

This module fetches an archived registry snapshot for a date and builds the nerve
complex two ways on the SAME snapshot (so representation is held constant and only
survivorship varies):
    - de-censored : every pool in the universe that day
    - survivor    : only pools still in today's registry (what the paper could see)

Caveats it is honest about:
  * Terra (May 2022) predates the earliest snapshot (Oct 2022) — not de-censorable.
  * Snapshots are ~weekly crawl dates, not daily; use for spot checks / coarse series,
    not the daily [-30,+30] permutation.
  * The 2022-23 archive represents Curve metapools with the LP token as its own vertex
    (FRAX-3CRV = {FRAX, 3CRV}), whereas today's API base-resolves them. So comparisons
    to the paper's base-resolved survivor numbers mix survivorship with representation;
    the de-censored-vs-survivor comparison HERE is clean (one snapshot, one
    representation). Controlling representation across eras is future work.

Run:
  python decensor.py --date 2023-03-07
  python decensor.py --series 2022-11-10 2023-03-07 2023-06-06 2023-11-28
"""
import argparse, gzip, itertools, json, math, urllib.request

import gudhi

import pipeline as P

UA = {"User-Agent": "defi-topology-research"}
ZERO = P.ZERO


def toks(p):
    return sorted(set(t.lower() for t in (p.get("underlyingTokens") or []) if t and t.lower() != ZERO))


def is_universe(p):
    return p.get("chain") == "Ethereum" and p.get("stablecoin") and 2 <= len(toks(p)) <= 8


def closest_snapshot(date_compact):
    """date_compact: 'YYYYMMDD'. Returns (timestamp, url) of the nearest archived
    registry snapshot, or (None, None)."""
    api = f"https://archive.org/wayback/available?url=yields.llama.fi/pools&timestamp={date_compact}"
    r = json.load(urllib.request.urlopen(urllib.request.Request(api, headers=UA), timeout=60))
    s = r.get("archived_snapshots", {}).get("closest", {})
    return s.get("timestamp"), s.get("url")


def fetch_registry(timestamp):
    """Fetch the raw archived JSON (via the id_ suffix, no Wayback toolbar) and parse.
    Handles gzip-compressed archived responses."""
    url = f"https://web.archive.org/web/{timestamp}id_/https://yields.llama.fi/pools"
    raw = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120).read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw)["data"]


def observables(pools, minshare=P.MINSHARE):
    """Nerve complex + observables directly from a registry snapshot (each pool carries
    tvlUsd at the snapshot instant). Mirrors pipeline.build_complex exactly."""
    live = [(toks(p), (p.get("tvlUsd") or 0)) for p in pools
            if is_universe(p) and (p.get("tvlUsd") or 0) > 0]
    total = sum(t for _, t in live)
    if total == 0:
        return None
    st = gudhi.SimplexTree(); verts = {}; edges = set(); ho = 0; used = 0
    for ts, tv in live:
        share = tv / total
        if share < minshare or len(ts) < 2:
            continue
        f = -math.log10(share); ids = []
        for t in ts:
            verts.setdefault(t, len(verts)); ids.append(verts[t])
        st.insert(ids, filtration=f); used += 1
        if len(ts) >= 3:
            ho += 1
        for e in itertools.combinations(sorted(ids), 2):
            edges.add(e)
    st.make_filtration_non_decreasing()
    st.compute_persistence(persistence_dim_max=True)
    b = st.betti_numbers(); b += [0] * (3 - len(b))
    V, E, C = len(verts), len(edges), b[0]
    skel = E - V + C
    return dict(universe=len(live), pools=used, ho_pools=ho, V=V, E=E,
                B0=b[0], essB1=b[1], essB2=b[2], skel=skel, gap=skel - b[1],
                ho_fraction=round((skel - b[1]) / skel, 3) if skel else 0.0)


def analyze_date(date_compact, today_ids):
    ts, url = closest_snapshot(date_compact)
    if not ts:
        print(f"{date_compact}: no snapshot"); return None
    reg = fetch_registry(ts)
    uni = [p for p in reg if is_universe(p)]
    surv = [p for p in uni if p["pool"] in today_ids]
    full_o, surv_o = observables(uni), observables(surv)
    return dict(snapshot=ts, n_universe=len(uni), n_survivor=len(surv),
                true_survivorship=round(len(surv) / len(uni), 3) if uni else 0,
                full=full_o, survivor=surv_o)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD single date")
    ap.add_argument("--series", nargs="+", help="multiple YYYY-MM-DD dates")
    args = ap.parse_args()
    today_ids = {u["pool"] for u in P.universe()}
    dates = args.series or ([args.date] if args.date else ["2023-03-07"])

    hdr = ("date", "snap", "trueUniv", "surv", "trueSv%",
           "essB1 f/s", "gap f/s", "HOfrac f/s")
    print(f"{hdr[0]:12s} {hdr[1]:>14} {hdr[2]:>8} {hdr[3]:>5} {hdr[4]:>7} "
          f"{hdr[5]:>12} {hdr[6]:>10} {hdr[7]:>13}")
    out = []
    for d in dates:
        r = analyze_date(d.replace("-", ""), today_ids)
        if not r:
            continue
        f, s = r["full"], r["survivor"]
        essb1 = f"{f['essB1']}/{s['essB1']}"
        gap = f"{f['gap']}/{s['gap']}"
        hof = f"{f['ho_fraction']}/{s['ho_fraction']}"
        print(f"{d:12s} {r['snapshot']:>14} {r['n_universe']:>8} {r['n_survivor']:>5} "
              f"{100*r['true_survivorship']:>6.1f}% {essb1:>12} {gap:>10} {hof:>13}")
        out.append({"date": d, **r})
    json.dump(out, open("decensor_series.json", "w"))


if __name__ == "__main__":
    main()
