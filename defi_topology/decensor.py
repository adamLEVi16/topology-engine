#!/usr/bin/env python3
"""
De-censoring DeFi survivorship bias via the Internet Archive  (v2 engine).

The paper's survivor-only reconstruction (and both AI reviews) assumed delisted pools
are unrecoverable from DeFiLlama. They are not: the Wayback Machine archived
`yields.llama.fi/pools` roughly weekly from Oct 2022, each snapshot being the FULL
universe at that date -- dead pools included -- with the identical schema. This module
rebuilds the nerve complex on the full historical universe and, per snapshot, isolates
the survivorship effect by also restricting to pools that survive to today.

Pieces:
  closest_snapshot / fetch_registry : locate + download an archived registry (cached,
                                      gzip-aware) to archive/ (git-ignored).
  observables                       : nerve-complex observables from a registry snapshot.
  build_series                      : de-censored + survivor observables over a schedule
                                      of target dates, deduped by actual snapshot.

Honest scope: snapshots are ~weekly crawl dates (not daily); Terra (May 2022) predates
the archive; the 2022-23 archive keeps LP tokens as their own vertices (FRAX-3CRV =
{FRAX, 3CRV}) whereas today's API base-resolves -- so within-archive comparisons are
clean but cross-era ones need representation control (see resolve_archive_lp, WIP).

Run:
  python decensor.py --build --start 2022-10-01 --end 2025-06-01 --step 30 \
                     --dense-start 2023-02-01 --dense-end 2023-04-20 --dense-step 7
  python decensor.py --series 2022-11-10 2023-03-07 2023-06-06 2023-11-28
  python decensor.py --pinned decensor_series.json    # exact byte-for-byte rebuild

Reproducibility note: the Wayback Machine is append-only, so resolving a target date to
its "closest crawl" (`--build`) can drift as new crawls are indexed. Each crawl timestamp,
however, addresses a fixed permanent snapshot; the timestamps used are recorded in the
series JSON, and `--pinned <series.json>` reproduces it exactly. Raw snapshots (~390 MB)
are cached under archive/ (git-ignored), re-fetched on demand.
"""
import argparse, datetime, gzip, itertools, json, math, os, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

import gudhi

import pipeline as P

UA = {"User-Agent": "defi-topology-research"}
ZERO = P.ZERO
HERE = os.path.dirname(os.path.abspath(__file__))
ARCHIVE_DIR = os.path.join(HERE, "archive")

# Curve 3pool LP token (identified from FRAX-3CRV in the archive). In the 2022-23
# archive it appears as its OWN vertex in ~68 metapools; resolving it into its base
# assets is the "resolved" fork the paper could not test because those metapools did
# not survive to today's (base-resolved) registry.
THREECRV = "0x6c3f90f043a72fa612cbac8115ee7e52bde6e490"


def resolve_lp(ts):
    """'resolved' fork: expand the 3CRV LP vertex into {DAI, USDC, USDT}. Default
    (lp_vertex fork) keeps 3CRV as its own vertex, the archive's native representation."""
    s = set(ts)
    if THREECRV in s:
        s.discard(THREECRV)
        s |= {P.DAI, P.USDC, P.USDT}
    return sorted(s)


# ---------------------------------------------------------------- universe filter
def toks(p):
    return sorted(set(t.lower() for t in (p.get("underlyingTokens") or []) if t and t.lower() != ZERO))


def is_universe(p):
    return p.get("chain") == "Ethereum" and p.get("stablecoin") and 2 <= len(toks(p)) <= 8


# ---------------------------------------------------------------- archive access
def closest_snapshot(date_compact, retries=3):
    """date_compact 'YYYYMMDD' -> (timestamp, url) of the nearest archived registry."""
    api = f"https://archive.org/wayback/available?url=yields.llama.fi/pools&timestamp={date_compact}"
    for r in range(retries):
        try:
            resp = json.load(urllib.request.urlopen(urllib.request.Request(api, headers=UA), timeout=60))
            s = resp.get("archived_snapshots", {}).get("closest", {})
            return s.get("timestamp"), s.get("url")
        except Exception:
            time.sleep(2 * (r + 1))
    return None, None


def fetch_registry(timestamp, retries=3):
    """Download (cached, gzip-aware) the raw archived registry for a snapshot timestamp.
    Returns the parsed `data` list, or None on failure."""
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    fn = os.path.join(ARCHIVE_DIR, f"{timestamp}.json")
    if os.path.exists(fn):
        return json.load(open(fn))
    url = f"https://web.archive.org/web/{timestamp}id_/https://yields.llama.fi/pools"
    for r in range(retries):
        try:
            raw = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=150).read()
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            data = json.loads(raw)["data"]
            json.dump(data, open(fn, "w"))
            return data
        except Exception:
            time.sleep(3 * (r + 1))
    return None


# ---------------------------------------------------------------- complex
def universe_tvl(pools):
    return sum((p.get("tvlUsd") or 0) for p in pools if is_universe(p))


def repair_transient_dips(mid, pre, post, frac=0.5, floor=1e5):
    """Data-quality guard for snapshots crawled during acute events. On the 2023-08-02
    crawl (mid Curve/Vyper exploit) 10 registry rows, 8 of them FRAX, had spuriously
    collapsed TVL that recovered by the next crawl (e.g. FRAX-USDC $435M->$73M->$451M);
    together they are 84% of the drop that halved universe TVL, and they inject a spurious
    ~8-loop jump in essential B1. (Counts are rows, not distinct pools: DeFiLlama re-lists
    the same Curve pool under Convex. Re-derive with paper_figures.py rather than trusting
    this comment.) For each
    pool materially live (> floor) on BOTH temporal neighbours, if its mid TVL is
    < frac * min(neighbours) it is treated as a transient dip and replaced by the
    neighbour mean. Returns (repaired_pools, n_fixed). Analogous to pipeline.forward_fill
    but at the registry-snapshot level. Only snapshots flagged by an integrity scan
    (universe TVL anomalously low vs neighbours) need this."""
    a = {p["pool"]: (p.get("tvlUsd") or 0) for p in pre}
    c = {p["pool"]: (p.get("tvlUsd") or 0) for p in post}
    out, nfix = [], 0
    for p in mid:
        q = dict(p); pid = p["pool"]; m = p.get("tvlUsd") or 0
        if a.get(pid, 0) > floor and c.get(pid, 0) > floor and m < frac * min(a[pid], c[pid]):
            q["tvlUsd"] = (a[pid] + c[pid]) / 2.0; nfix += 1
        out.append(q)
    return out, nfix


def observables(pools, minshare=P.MINSHARE, resolve=False):
    """Nerve-complex observables from a registry snapshot (each pool carries tvlUsd at
    the snapshot instant). Mirrors pipeline.build_complex exactly. resolve=True applies
    the 3CRV -> base-assets fork before building."""
    live = [((resolve_lp(toks(p)) if resolve else toks(p)), (p.get("tvlUsd") or 0))
            for p in pools if is_universe(p) and (p.get("tvlUsd") or 0) > 0]
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
                ho_fraction=round((skel - b[1]) / skel, 4) if skel else 0.0)


# ---------------------------------------------------------------- schedule + series
def month_targets(start, end, step_days=30):
    d0 = datetime.date.fromisoformat(start); d1 = datetime.date.fromisoformat(end)
    out, d = [], d0
    while d <= d1:
        out.append(d.strftime("%Y%m%d")); d += datetime.timedelta(days=step_days)
    return out


def cache_all(targets, workers=4):
    """Resolve each target date to its nearest snapshot, download+cache, dedupe by the
    actual snapshot timestamp. Returns {timestamp: data} for successful fetches."""
    ts_set = {}
    def resolve(t):
        ts, _ = closest_snapshot(t)
        return ts
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for t, ts in zip(targets, ex.map(resolve, targets)):
            if ts:
                ts_set[ts] = None
    uniq = sorted(ts_set)
    print(f"  {len(targets)} targets -> {len(uniq)} distinct snapshots; downloading...")
    def get(ts):
        return ts, fetch_registry(ts)
    got = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for ts, data in ex.map(get, uniq):
            if data:
                got[ts] = data
    print(f"  cached {len(got)}/{len(uniq)} snapshots")
    return got


def build_series(targets=None, out="decensor_series.json", tvl_frac=0.6, pinned=None):
    today_ids = {u["pool"] for u in P.universe()}
    if pinned:
        # exact reproducibility: rebuild from the snapshot timestamps recorded in an
        # existing series JSON. fetch_registry(ts) serves a SPECIFIC Wayback crawl and is
        # deterministic, so this reproduces the series byte-for-byte regardless of how the
        # live "closest crawl" resolution has drifted since.
        want = sorted({r["snapshot"] for r in json.load(open(pinned))})
        snaps = {ts: d for ts, d in ((t, fetch_registry(t)) for t in want) if d}
        print(f"  pinned rebuild: {len(snaps)}/{len(want)} exact snapshots from {pinned}")
    else:
        snaps = cache_all(targets)
    tss = sorted(snaps)

    # integrity scan: flag snapshots whose universe TVL craters vs temporal neighbours
    # (corrupted event-window crawls, e.g. 2023-08-02) and repair them from neighbours
    # BEFORE computing observables, so the descriptive 2x2/series gets the same data
    # hygiene as the event tests and the representation figure.
    utvl = {ts: universe_tvl(snaps[ts]) for ts in tss}
    repaired_ts = []
    for i, ts in enumerate(tss):
        if i == 0 or i == len(tss) - 1:
            continue
        nb = [utvl[tss[j]] for j in (i - 1, i + 1)]
        if min(nb) > 0 and utvl[ts] < tvl_frac * (sorted(nb)[len(nb) // 2]):
            snaps[ts], nfix = repair_transient_dips(snaps[ts], snaps[tss[i - 1]], snaps[tss[i + 1]])
            if nfix:
                repaired_ts.append(ts)
    if repaired_ts:
        print(f"  integrity: repaired {len(repaired_ts)} corrupted crawl(s): {repaired_ts}")

    rows = []
    for ts in tss:
        data = snaps[ts]
        uni = [p for p in data if is_universe(p)]
        if not uni:
            continue
        surv = [p for p in uni if p["pool"] in today_ids]
        date = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
        rows.append({"date": date, "snapshot": ts,
                     "n_universe": len(uni), "n_survivor": len(surv),
                     "true_survivorship": round(len(surv) / len(uni), 4),
                     "full": observables(uni), "survivor": observables(surv)})
    with open(out, "w") as fh:
        json.dump(rows, fh)
    if not rows:
        print(f"\nwrote {out}: 0 snapshots (no data for these targets)")
        return rows
    print(f"\nwrote {out}: {len(rows)} snapshots ({rows[0]['date']} .. {rows[-1]['date']})")
    hdr = ("date", "univ", "surv", "sv%", "essB1 f/s", "gap f/s", "HOfrac f/s")
    print(f"{hdr[0]:11s}{hdr[1]:>5}{hdr[2]:>5}{hdr[3]:>6}{hdr[4]:>13}{hdr[5]:>11}{hdr[6]:>15}")
    for r in rows:
        f, s = r["full"], r["survivor"]
        eb = f"{f['essB1']}/{s['essB1']}"
        gp = f"{f['gap']}/{s['gap']}"
        hf = f"{f['ho_fraction']:.2f}/{s['ho_fraction']:.2f}"
        print(f"{r['date']:11s}{r['n_universe']:>5}{r['n_survivor']:>5}"
              f"{100*r['true_survivorship']:>5.0f}%{eb:>13}{gp:>11}{hf:>15}")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--start", default="2022-10-01")
    ap.add_argument("--end", default="2025-06-01")
    ap.add_argument("--step", type=int, default=30)
    ap.add_argument("--dense-start", default=None)
    ap.add_argument("--dense-end", default=None)
    ap.add_argument("--dense-step", type=int, default=7)
    ap.add_argument("--series", nargs="+")
    ap.add_argument("--pinned", default=None,
                    help="rebuild EXACTLY from the snapshot timestamps recorded in an "
                         "existing series JSON (deterministic; ignores --start/--end/--dense)")
    ap.add_argument("--out", default="decensor_series.json")
    args = ap.parse_args()

    if args.pinned:
        build_series(out=args.out, pinned=args.pinned)
    elif args.build:
        targets = month_targets(args.start, args.end, args.step)
        if args.dense_start and args.dense_end:
            targets += month_targets(args.dense_start, args.dense_end, args.dense_step)
        build_series(sorted(set(targets)), args.out)
    elif args.series:
        build_series([d.replace("-", "") for d in args.series], args.out)
    else:
        build_series(["20230307"], args.out)


if __name__ == "__main__":
    main()
