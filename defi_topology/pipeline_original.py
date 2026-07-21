#!/usr/bin/env python3
"""
DeFi topology MVP — end-to-end pipeline (blueprint v2).

Builds daily simplicial complexes from surviving Ethereum stablecoin liquidity
pools around a stress event, using a level-invariant (TVL-share) filtration, and
tracks the observables that actually carry content on this object:

    - essential B1            (loops; infinite-persistence classes)
    - 1-skeleton cycle rank   (E - V + B0)  and the higher-order gap
    - H0 total persistence    (connectivity / merging dynamics)

WHY NOT persistence landscapes: on this structural complex every H1 class is
essential (infinite bar), so landscape / L^p summaries evaluate to ~0. Track
essential Betti numbers + H0 persistence instead. (See RESULTS.md, finding 2.)

Data: DeFiLlama, free, no auth.
    registry : https://yields.llama.fi/pools
    history  : https://yields.llama.fi/chart/{pool}   (daily TVL, back to ~Feb 2022)

Deps: pip install --break-system-packages gudhi matplotlib
Run  : python defi_topology_pipeline.py --event 2023-03-11 --control 2023-01-11
       python defi_topology_pipeline.py --event 2022-05-10 --control 2022-03-10   # Terra
"""
import argparse, datetime, itertools, json, math, os, statistics as S, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

import gudhi
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

ZERO = "0x0000000000000000000000000000000000000000"
UA = {"User-Agent": "defi-topology-research"}
CHART_DIR = "charts"
MINSHARE = 1e-5          # size cap: drop dust below this share of daily universe TVL


def _get(url):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90))


def tokens(p):
    return sorted(set(t.lower() for t in (p.get("underlyingTokens") or []) if t and t.lower() != ZERO))


def universe():
    """Ethereum, stablecoin-flagged pools with 2..8 underlying tokens (the MVP universe)."""
    pools = _get("https://yields.llama.fi/pools")["data"]
    uni = [p for p in pools
           if p.get("chain") == "Ethereum" and p.get("stablecoin") and 2 <= len(tokens(p)) <= 8]
    return [{"pool": p["pool"], "toks": tokens(p), "sym": p["symbol"], "proj": p["project"]} for p in uni]


def fetch_charts(uni, workers=6, rounds=6):
    """Cache per-pool daily TVL history to CHART_DIR. Rate-limited endpoint -> retry loop."""
    os.makedirs(CHART_DIR, exist_ok=True)

    def one(u):
        fn = f"{CHART_DIR}/{u['pool']}.json"
        if os.path.exists(fn):
            return
        try:
            d = _get(f"https://yields.llama.fi/chart/{u['pool']}")["data"]
            json.dump([(c["timestamp"][:10], c.get("tvlUsd") or 0) for c in d], open(fn, "w"))
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


def load_charts(have):
    return {u["pool"]: dict(json.load(open(f"{CHART_DIR}/{u['pool']}.json"))) for u in have}


def day_metrics(ds, charts, tok):
    """One day's share-weighted complex -> topological observables, or None if no data."""
    live = {pid: charts[pid].get(ds, 0) for pid in charts}
    live = {pid: v for pid, v in live.items() if v > 0}
    total = sum(live.values())
    if total == 0:
        return None
    st = gudhi.SimplexTree(); verts = {}; edges = set(); n_ho = 0
    for pid, v in live.items():
        share = v / total
        if share < MINSHARE:
            continue
        ts = tok[pid]
        if len(ts) < 2:
            continue
        f = -math.log10(share)                 # strong pools enter first (low epsilon)
        ids = []
        for t in ts:
            verts.setdefault(t, len(verts)); ids.append(verts[t])
        st.insert(ids, filtration=f)
        if len(ts) >= 3:
            n_ho += 1
        for e in itertools.combinations(sorted(ids), 2):
            edges.add(e)
    st.make_filtration_non_decreasing()
    st.compute_persistence(persistence_dim_max=True)
    b = st.betti_numbers(); b += [0] * (2 - len(b))
    h0 = [(bb, d) for (dim, (bb, d)) in st.persistence() if dim == 0 and d != float("inf")]
    V, E, C = len(verts), len(edges), b[0]
    skel = E - V + C
    return dict(date=ds, tvl=total, pools=len([1 for v in live.values() if v / total >= MINSHARE]),
                ho_pools=n_ho, V=V, E=E, B0=b[0], essB1=b[1], skel=skel, gap=skel - b[1],
                tp0=sum(d - bb for bb, d in h0))


def window(center, charts, tok, half=30):
    out = []
    for dd in range(-half, half + 1):
        r = day_metrics((center + datetime.timedelta(dd)).isoformat(), charts, tok)
        if r:
            out.append(r)
    return out


def survivorship(date_iso, charts):
    """Fraction of TODAY's universe that was live on `date_iso`.
    NB: this is 'how many current pools are old enough', an UPPER bound on usable
    history. True survivorship (fraction of that era's pools that live on) is NOT
    recoverable from this API -- delisted pools are gone. State this as a limit."""
    live = sum(1 for pid in charts if charts[pid].get(date_iso, 0) > 0)
    return live, len(charts)


def plot(event, control, event_date, path):
    D = [datetime.date.fromisoformat(r["date"]) for r in event]
    dep = datetime.date.fromisoformat(event_date)
    cb = S.mean(r["essB1"] for r in control) if control else None
    ct = S.mean(r["tp0"] for r in control) if control else None
    fig, ax = plt.subplots(4, 1, figsize=(11, 12), sharex=True)
    ax[0].plot(D, [r["essB1"] for r in event], color="#1f77b4", lw=2, marker=".")
    if cb is not None: ax[0].axhline(cb, color="gray", ls=":", label=f"control mean={cb:.2f}"); ax[0].legend(fontsize=9)
    ax[0].set_ylabel("essential B₁")
    ax[0].set_title(f"DeFi stablecoin liquidity topology around {event_date}\n"
                    "survivor-only universe, TVL-share filtration", fontsize=11)
    ax[1].plot(D, [r["gap"] for r in event], color="#2ca02c", lw=2, marker=".")
    ax[1].set_ylabel("higher-order gap\n(skeleton − essB₁)")
    ax[2].plot(D, [r["tp0"] for r in event], color="#9467bd", lw=2, marker=".")
    if ct is not None: ax[2].axhline(ct, color="gray", ls=":")
    ax[2].set_ylabel("H₀ total persistence")
    ax[3].plot(D, [r["tvl"] / 1e9 for r in event], color="#555")
    ax[3].set_ylabel("universe TVL ($B)")
    for a in ax:
        a.axvline(dep, color="crimson", ls="--"); a.grid(alpha=.25)
    plt.tight_layout(); plt.savefig(path, dpi=140, bbox_inches="tight"); plt.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", default="2023-03-11", help="event date YYYY-MM-DD")
    ap.add_argument("--control", default="2023-01-11", help="matched calm-period date")
    ap.add_argument("--half", type=int, default=30, help="half-window in days")
    ap.add_argument("--tag", default=None, help="output filename tag (default: event date)")
    args = ap.parse_args()
    tag = args.tag or args.event

    print("1/4 registry ..."); uni = universe(); print(f"  universe: {len(uni)} pools")
    print("2/4 charts ...");   have = fetch_charts(uni)
    charts = load_charts(have); tok = {u["pool"]: u["toks"] for u in have}

    ev = datetime.date.fromisoformat(args.event)
    live, tot = survivorship(args.event, charts)
    print(f"3/4 survivorship: {live}/{tot} of today's pools were live on {args.event} "
          f"({100*live/tot:.1f}%)  [upper bound on usable history]")

    event = window(ev, charts, tok, args.half)
    control = window(datetime.date.fromisoformat(args.control), charts, tok, args.half)

    def m(rows, k): return (S.mean(r[k] for r in rows), S.pstdev([r[k] for r in rows]) if len(rows) > 1 else 0)
    print("4/4 observables (event vs control):")
    for k in ["essB1", "skel", "gap", "tp0", "pools"]:
        em, es = m(event, k); cm, cs = m(control, k)
        print(f"    {k:6s}  {em:8.2f}±{es:5.2f}   vs   {cm:8.2f}±{cs:5.2f}")

    json.dump({"event": event, "control": control,
               "survivorship": {"live": live, "total": tot, "date": args.event}},
              open(f"{tag}_series.json", "w"))
    plot(event, control, args.event, f"{tag}_topology.png")
    print(f"\nwrote {tag}_series.json and {tag}_topology.png")


if __name__ == "__main__":
    main()
