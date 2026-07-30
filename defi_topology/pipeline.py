#!/usr/bin/env python3
"""
DeFi topology pipeline — hardened build (blueprint v2, extended).

This is the v2 pipeline with the fixes and extensions requested after the first
USDC-depeg run. It is a strict superset of `pipeline_original.py`; the observables
it emits for lp_mode="resolved", coverage_frac=0 reduce to the originals.

Extensions over the MVP:
  1. Data-gap forward-fill (`forward_fill`) — a missing/one-day-zero per-pool sample
     no longer drops the pool from the universe. This fixes the 2023-02-11 essB1=0
     artifact (that day lost ~16 pools to missing chart samples) at the source.
  2. B2 is computed and reported (blueprint predicts B2 == 0 throughout — now checked
     rather than assumed), and the skeleton-vs-nerve decomposition is the headline
     output: cycle rank of the 1-skeleton (E - V + B0) vs nerve B1, and the gap.
  3. LP-resolution fork (`--lp`): "resolved" uses DeFiLlama's underlyingTokens as-is
     (already base-asset resolved); "lp_vertex" re-collapses recognised LP baskets
     (3CRV) back into a single vertex, which is the blueprint's intended DEFAULT.
     See METHODS.md for why the two are inverted from what §6.1 assumed.
  4. Per-day coverage diagnostic + window-level coverage guard.

Inference (placebo-window permutation, block bootstrap) is in `inference.py`;
threshold/window robustness sweeps are in `robustness.py`.

Deps: python -m venv venv && source venv/bin/activate; pip install -r requirements.txt
Run  : python pipeline.py --event 2023-03-11 --placebo 2022-08-15 --lp resolved --tag usdc
"""
import argparse, datetime, itertools, json, math, os, statistics as S, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

import gudhi
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

ZERO = "0x0000000000000000000000000000000000000000"
UA = {"User-Agent": "defi-topology-research"}
HERE = os.path.dirname(os.path.abspath(__file__))
CHART_DIR = os.path.join(HERE, "charts")
MINSHARE = 1e-5           # dust cap: drop pools below this share of daily universe TVL
MAX_GAP = 3               # forward-fill interior gaps up to this many consecutive days

# --- canonical Ethereum-mainnet addresses used by the LP-vertex fork ------------------
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
DAI  = "0x6b175474e89094c44da98b954eedeac495271d0f"
# LP token -> the base-asset set DeFiLlama resolves it into. DeFiLlama's `underlyingTokens`
# already resolves wrappers to base assets, so keeping an LP token as its own vertex (the
# blueprint's stated default) means RE-COLLAPSING these baskets when they appear as a
# proper subset of a larger (meta)pool. Curated + extensible; 3CRV dominates per §6.0.
LP_BASES = {"3CRV": frozenset({DAI, USDC, USDT})}


# ====================================================================================
# data access
# ====================================================================================
def _get(url):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90))


def tokens(p):
    return sorted(set(t.lower() for t in (p.get("underlyingTokens") or []) if t and t.lower() != ZERO))


def universe():
    """Ethereum stablecoin-flagged pools with 2..8 underlying tokens. Reuses the cached
    registry (charts/universe.json) written by _fetch.py when present."""
    cached = os.path.join(CHART_DIR, "universe.json")
    if os.path.exists(cached):
        return json.load(open(cached))
    pools = _get("https://yields.llama.fi/pools")["data"]
    uni = [p for p in pools
           if p.get("chain") == "Ethereum" and p.get("stablecoin") and 2 <= len(tokens(p)) <= 8]
    return [{"pool": p["pool"], "toks": tokens(p), "sym": p["symbol"], "proj": p["project"]} for p in uni]


def write_json_atomic(path, obj):
    """Write JSON via a temp file + os.replace, which is atomic on POSIX.

    The cache is keyed on os.path.exists(), so a half-written file is worse than no file:
    it is trusted forever and json.load raises on every later run until someone deletes it
    by hand. That is reachable here -- these fetches run in ephemeral containers and get
    interrupted. Writing to <path>.tmp and renaming means a crash leaves either the old
    file or no file, never a truncated one."""
    tmp = f"{path}.tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh)
    os.replace(tmp, path)


def read_json_cache(path):
    """Load a cache file, treating a corrupted one as absent so it gets re-fetched rather
    than raising on every subsequent run."""
    try:
        with open(path) as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


def fetch_charts(uni, workers=6, rounds=8):
    os.makedirs(CHART_DIR, exist_ok=True)

    def one(u):
        fn = f"{CHART_DIR}/{u['pool']}.json"
        if os.path.exists(fn):
            return
        try:
            d = _get(f"https://yields.llama.fi/chart/{u['pool']}")["data"]
            write_json_atomic(fn, [(c["timestamp"][:10], c.get("tvlUsd") or 0) for c in d])
        except Exception:
            pass

    for r in range(rounds):
        miss = [u for u in uni if not os.path.exists(f"{CHART_DIR}/{u['pool']}.json")]
        if not miss:
            break
        print(f"  fetch round {r}: {len(miss)} remaining")
        with ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(one, miss))
        time.sleep(3)
    have = [u for u in uni if os.path.exists(f"{CHART_DIR}/{u['pool']}.json")]
    print(f"  charts cached: {len(have)}/{len(uni)}")
    return have


def forward_fill(observed, max_gap=MAX_GAP):
    """observed: dict 'YYYY-MM-DD' -> tvl (raw daily samples, may include 0s and gaps).

    Return a dict over the pool's ACTIVE span (first..last day with tvl>0) in which
    interior missing days (absent samples, or one-off zeros bracketed by positive
    values) of length <= max_gap are filled by the last positive value. Days before
    the pool's first positive sample or after its last are left absent (genuinely not
    live). This removes single-day data holes without resurrecting a truly dead pool.
    """
    pos = sorted(d for d, v in observed.items() if v and v > 0)
    if not pos:
        return {}
    first, last = pos[0], pos[-1]
    d0 = datetime.date.fromisoformat(first)
    d1 = datetime.date.fromisoformat(last)
    out, last_pos, gap = {}, None, 0
    day = d0
    while day <= d1:
        ds = day.isoformat()
        v = observed.get(ds, 0) or 0
        if v > 0:
            out[ds] = v; last_pos = v; gap = 0
        elif last_pos is not None and gap < max_gap:
            out[ds] = last_pos; gap += 1        # fill interior hole
        # else: leave absent (gap too long -> treat as not live)
        day += datetime.timedelta(days=1)
    return out


def repair_universe_dips(charts, tvl_frac=0.6, pool_frac=0.5):
    """Daily analogue of decensor.repair_transient_dips, kept deliberately conservative so
    it can never erase real event dynamics. First flag whole days on which the *universe*
    TVL craters vs its immediate neighbours (total < tvl_frac x neighbour median) -- these
    are DeFiLlama data glitches, e.g. 2023-08-02 (mid Curve/Vyper exploit) and 2023-12-17.
    A real depeg's TVL decline is gradual and is not flagged. Only on a flagged day, repair
    each pool whose TVL is a transient dip (< pool_frac x min of its two neighbours) by
    neighbour interpolation. Returns (charts, flagged_days); modifies charts in place."""
    dates = sorted(set().union(*[set(c) for c in charts.values()])) if charts else []
    tot = {d: sum(c.get(d, 0) for c in charts.values()) for d in dates}
    flagged = []
    for i, d in enumerate(dates):
        nb = [tot[dates[j]] for j in (i - 1, i + 1) if 0 <= j < len(dates)]
        med = sorted(nb)[len(nb) // 2] if nb else tot[d]
        if med > 0 and tot[d] < tvl_frac * med:
            flagged.append(d)
    for d in flagged:
        i = dates.index(d)
        if i == 0 or i == len(dates) - 1:
            continue                      # need both neighbours to interpolate; leave edge anomalies as-is
        dprev, dnext = dates[i - 1], dates[i + 1]
        for c in charts.values():
            a, m, cc = c.get(dprev, 0), c.get(d, 0), c.get(dnext, 0)
            if a > 0 and cc > 0 and m < pool_frac * min(a, cc):
                c[d] = (a + cc) / 2.0
    return charts, flagged


def load_charts(have, fill=True, max_gap=MAX_GAP, repair_dips=True):
    """Load per-pool {date: tvl}. With fill=True, forward-fill short interior gaps
    (zeros/absent days); with repair_dips=True, also repair universe-flagged transient
    TVL dips (positive-value glitches forward_fill cannot see), matching the de-censored
    path's data hygiene."""
    out = {}
    for u in have:
        raw = dict(json.load(open(f"{CHART_DIR}/{u['pool']}.json")))
        out[u["pool"]] = forward_fill(raw, max_gap) if fill else raw
    if repair_dips:
        out, _ = repair_universe_dips(out)
    return out


# ====================================================================================
# complex construction
# ====================================================================================
def resolve_tokens(ts, lp_mode):
    """Apply the LP-resolution fork to a pool's token set.
      resolved : DeFiLlama base-asset tokens as-is.
      lp_vertex: collapse any recognised LP basket that appears as a STRICT subset
                 (i.e. a metapool) into a single synthetic LP vertex; a standalone
                 basket (e.g. the bare 3pool == {DAI,USDC,USDT}) is left intact."""
    s = set(ts)
    if lp_mode == "lp_vertex":
        for lp, base in LP_BASES.items():
            if base < s:                        # strict subset -> metapool
                s = (s - set(base)) | {lp}
    return sorted(s)


def build_complex(shares, tok, minshare, lp_mode):
    """shares: {pool_id: share_of_universe_tvl}. Returns (SimplexTree, verts, edges,
    n_ho, used). Each contributing pool inserts a FILLED simplex on its (resolved)
    token set at filtration -log10(share) — the nerve construction."""
    st = gudhi.SimplexTree(); verts = {}; edges = set(); n_ho = 0; used = 0
    for pid, share in shares.items():
        if share < minshare:
            continue
        ts = resolve_tokens(tok[pid], lp_mode)
        if len(ts) < 2:
            continue
        f = -math.log10(share)                  # strong pools enter first (low epsilon)
        ids = []
        for t in ts:
            verts.setdefault(t, len(verts)); ids.append(verts[t])
        st.insert(ids, filtration=f)
        used += 1
        if len(ts) >= 3:
            n_ho += 1
        for e in itertools.combinations(sorted(ids), 2):
            edges.add(e)
    return st, verts, edges, n_ho, used


def day_metrics(ds, charts, tok, minshare=MINSHARE, lp_mode="resolved"):
    """One day's share-weighted complex -> topological observables, or None if no data."""
    live = {pid: charts[pid].get(ds, 0) for pid in charts}
    live = {pid: v for pid, v in live.items() if v > 0}
    total = sum(live.values())
    if total == 0:
        return None
    shares = {pid: v / total for pid, v in live.items()}
    st, verts, edges, n_ho, used = build_complex(shares, tok, minshare, lp_mode)
    st.make_filtration_non_decreasing()
    st.compute_persistence(persistence_dim_max=True)
    b = st.betti_numbers(); b += [0] * (3 - len(b))        # B0, B1, B2
    h0 = [(bb, d) for (dim, (bb, d)) in st.persistence() if dim == 0 and d != float("inf")]
    V, E, C = len(verts), len(edges), b[0]
    skel = E - V + C
    return dict(date=ds, tvl=total, pools=used, ho_pools=n_ho, live_raw=len(live),
                V=V, E=E, B0=b[0], essB1=b[1], essB2=b[2],
                skel=skel, gap=skel - b[1], tp0=sum(d - bb for bb, d in h0))


def window(center, charts, tok, half=30, minshare=MINSHARE, lp_mode="resolved",
           coverage_frac=0.75):
    """Daily observables over [center-half, center+half]. Days whose live-pool coverage
    falls below coverage_frac * (window median) are treated as data gaps and dropped;
    their dates are returned separately. With forward-fill upstream this should be rare."""
    raw = []
    for dd in range(-half, half + 1):
        r = day_metrics((center + datetime.timedelta(dd)).isoformat(), charts, tok, minshare, lp_mode)
        if r:
            raw.append(r)
    if not raw:
        return [], []
    med = S.median(r["live_raw"] for r in raw)
    kept = [r for r in raw if r["live_raw"] >= coverage_frac * med]
    dropped = [r["date"] for r in raw if r["live_raw"] < coverage_frac * med]
    return kept, dropped


def survivorship(date_iso, charts):
    """Fraction of TODAY's universe live on `date_iso`. This is an UPPER bound on usable
    history ('how many current pools are old enough'), NOT true survivorship — delisted
    pools are unrecoverable from this API. State as a limit."""
    live = sum(1 for pid in charts if charts[pid].get(date_iso, 0) > 0)
    return live, len(charts)


# ====================================================================================
# reporting
# ====================================================================================
def plot(event, placebo, event_date, path):
    D = [datetime.date.fromisoformat(r["date"]) for r in event]
    dep = datetime.date.fromisoformat(event_date)
    cb = S.mean(r["essB1"] for r in placebo) if placebo else None
    ct = S.mean(r["tp0"] for r in placebo) if placebo else None
    fig, ax = plt.subplots(4, 1, figsize=(11, 12), sharex=True)
    ax[0].plot(D, [r["essB1"] for r in event], color="#1f77b4", lw=2, marker=".")
    if cb is not None:
        ax[0].axhline(cb, color="gray", ls=":", label=f"placebo mean={cb:.2f}"); ax[0].legend(fontsize=9)
    ax[0].set_ylabel("essential B₁")
    ax[0].set_title(f"DeFi stablecoin liquidity topology around {event_date}\n"
                    "survivor-only universe, TVL-share filtration", fontsize=11)
    ax[1].plot(D, [r["gap"] for r in event], color="#2ca02c", lw=2, marker=".")
    ax[1].set_ylabel("higher-order gap\n(skeleton − essB₁)")
    ax[2].plot(D, [r["tp0"] for r in event], color="#9467bd", lw=2, marker=".")
    if ct is not None:
        ax[2].axhline(ct, color="gray", ls=":")
    ax[2].set_ylabel("H₀ total persistence")
    ax[3].plot(D, [r["tvl"] / 1e9 for r in event], color="#555")
    ax[3].set_ylabel("universe TVL ($B)")
    for a in ax:
        a.axvline(dep, color="crimson", ls="--"); a.grid(alpha=.25)
    plt.tight_layout(); plt.savefig(path, dpi=140, bbox_inches="tight"); plt.close()


def _summ(rows, k):
    vals = [r[k] for r in rows]
    return (S.mean(vals), S.pstdev(vals) if len(vals) > 1 else 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", default="2023-03-11", help="event date YYYY-MM-DD")
    ap.add_argument("--placebo", default=None,
                    help="independent calm-period date for the placebo window (NOT the "
                         "adjacent pre-event window). Optional.")
    ap.add_argument("--half", type=int, default=30, help="half-window in days")
    ap.add_argument("--minshare", type=float, default=MINSHARE, help="dust cap (share)")
    ap.add_argument("--lp", choices=["resolved", "lp_vertex"], default="resolved",
                    help="LP-resolution fork")
    ap.add_argument("--coverage-frac", type=float, default=0.75,
                    help="drop days below this fraction of the window median coverage")
    ap.add_argument("--no-fill", action="store_true", help="disable gap forward-fill")
    ap.add_argument("--tag", default=None, help="output filename tag")
    args = ap.parse_args()
    tag = args.tag or args.event

    print("1/4 registry ..."); uni = universe(); print(f"  universe: {len(uni)} pools")
    print("2/4 charts ...");   have = fetch_charts(uni)
    charts = load_charts(have, fill=not args.no_fill)
    tok = {u["pool"]: u["toks"] for u in have}

    ev = datetime.date.fromisoformat(args.event)
    live, tot = survivorship(args.event, charts)
    print(f"3/4 survivorship: {live}/{tot} of today's pools live on {args.event} "
          f"({100*live/tot:.1f}%)  [upper bound on usable history]")

    event, ev_drop = window(ev, charts, tok, args.half, args.minshare, args.lp, args.coverage_frac)
    placebo, pb_drop = ([], [])
    if args.placebo:
        placebo, pb_drop = window(datetime.date.fromisoformat(args.placebo), charts, tok,
                                  args.half, args.minshare, args.lp, args.coverage_frac)
    if ev_drop:
        print(f"  coverage-guard dropped {len(ev_drop)} event day(s): {ev_drop}")

    print(f"4/4 observables (lp={args.lp}, minshare={args.minshare:g}) "
          f"event{'' if not placebo else ' vs placebo'}:")
    for k in ["essB1", "essB2", "skel", "gap", "tp0", "pools"]:
        em, es = _summ(event, k)
        line = f"    {k:6s}  {em:8.2f}±{es:5.2f}"
        if placebo:
            cm, cs = _summ(placebo, k)
            line += f"   vs   {cm:8.2f}±{cs:5.2f}"
        print(line)

    out = {"event": event, "placebo": placebo,
           "meta": {"event_date": args.event, "placebo_date": args.placebo,
                    "lp_mode": args.lp, "minshare": args.minshare, "half": args.half,
                    "fill": not args.no_fill, "dropped_days": ev_drop + pb_drop},
           "survivorship": {"live": live, "total": tot, "date": args.event}}
    json.dump(out, open(f"{tag}_series.json", "w"))
    plot(event, placebo, args.event, f"{tag}_topology.png")
    print(f"\nwrote {tag}_series.json and {tag}_topology.png")


if __name__ == "__main__":
    main()
