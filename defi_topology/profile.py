#!/usr/bin/env python3
"""
RQ1 headline figure: the skeleton-vs-nerve decomposition as a function of the
filtration threshold, at snapshot dates.

For each snapshot date and each share threshold s (log-spaced), build the day's
complex including only pools with TVL-share >= s, and record:

    skel  = cycle rank of the 1-skeleton (E - V + B0)   [pairwise loop count]
    B1    = nerve Betti-1                                [loops surviving fills]
    gap   = skel - B1                                    [loops filled by >=3-asset pools]

The curves answer RQ1 by measurement: how much of the loop structure is genuinely
higher-order, at what liquidity depth does it live, and is it a fixed property of the
network across regimes (Terra crash, USDC depeg, calm periods)?

Writes figs/rq1_profile.png and rq1_profile.json.

Run:  python profile.py
      python profile.py --dates 2022-05-10 2023-03-11 2023-06-15
"""
import argparse, json, math, os

import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

import pipeline as P

DEFAULT_DATES = ["2022-05-10", "2022-09-15", "2023-03-11", "2023-06-15", "2023-12-15"]
DATE_LABELS = {"2022-05-10": "Terra/UST crash", "2022-09-15": "calm 2022",
               "2023-03-11": "USDC depeg", "2023-06-15": "calm 2023",
               "2023-12-15": "late 2023"}


def thresholds(lo_exp=-6.0, hi_exp=-1.0, per_decade=8):
    n = int((hi_exp - lo_exp) * per_decade) + 1
    return [10 ** (lo_exp + i / per_decade) for i in range(n)]


def day_profile(ds, charts, tok, ths, lp_mode="resolved"):
    live = {pid: charts[pid].get(ds, 0) for pid in charts}
    live = {pid: v for pid, v in live.items() if v > 0}
    total = sum(live.values())
    if total == 0:
        return None
    shares = {pid: v / total for pid, v in live.items()}
    rows = []
    for s in ths:
        st, verts, edges, n_ho, used = P.build_complex(shares, tok, s, lp_mode)
        if len(verts) == 0:
            rows.append(dict(th=s, V=0, E=0, B0=0, B1=0, skel=0, gap=0, pools=0))
            continue
        st.make_filtration_non_decreasing()
        st.compute_persistence(persistence_dim_max=True)
        b = st.betti_numbers(); b += [0] * (2 - len(b))
        V, E = len(verts), len(edges)
        skel = E - V + b[0]
        rows.append(dict(th=s, V=V, E=E, B0=b[0], B1=b[1], skel=skel,
                         gap=skel - b[1], pools=used))
    return rows


def plot(profiles, path):
    n = len(profiles)
    fig, axes = plt.subplots(1, n, figsize=(3.4 * n, 3.6), sharey=True)
    if n == 1:
        axes = [axes]
    for ax, (ds, rows) in zip(axes, profiles.items()):
        th = [r["th"] for r in rows]
        ax.plot(th, [r["skel"] for r in rows], color="#2ca02c", lw=1.8,
                label="1-skeleton cycle rank")
        ax.plot(th, [r["B1"] for r in rows], color="#1f77b4", lw=1.8, label="nerve B₁")
        ax.fill_between(th, [r["B1"] for r in rows], [r["skel"] for r in rows],
                        color="#2ca02c", alpha=0.18, label="higher-order gap")
        ax.axvline(P.MINSHARE, color="gray", ls=":", lw=1)
        ax.set_xscale("log")
        ax.invert_xaxis()                       # deep liquidity (high share) on the left
        ax.set_title(f"{ds}\n{DATE_LABELS.get(ds, '')}", fontsize=10)
        ax.set_xlabel("TVL-share threshold")
        ax.grid(alpha=.25)
    axes[0].set_ylabel("independent loops")
    axes[0].legend(fontsize=8, loc="upper left")
    fig.suptitle("Skeleton-vs-nerve loop decomposition across the share filtration "
                 "(survivor-reconstructed universe)", fontsize=11)
    plt.tight_layout()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    plt.savefig(path, dpi=160, bbox_inches="tight"); plt.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", nargs="+", default=DEFAULT_DATES)
    ap.add_argument("--out", default="figs/rq1_profile.png")
    args = ap.parse_args()

    uni = P.universe(); have = P.fetch_charts(uni)
    charts = P.load_charts(have); tok = {u["pool"]: u["toks"] for u in have}
    ths = thresholds()

    profiles = {}
    for ds in args.dates:
        rows = day_profile(ds, charts, tok, ths)
        if rows is None:
            print(f"  {ds}: no data, skipped"); continue
        profiles[ds] = rows
        at_op = min(rows, key=lambda r: abs(math.log10(r["th"]) - math.log10(P.MINSHARE)))
        frac = at_op["gap"] / at_op["skel"] if at_op["skel"] else float("nan")
        print(f"  {ds}: at operating threshold {P.MINSHARE:g}: skel={at_op['skel']} "
              f"B1={at_op['B1']} gap={at_op['gap']} ({100*frac:.0f}% of loops are higher-order fills)")

    json.dump(profiles, open("rq1_profile.json", "w"))
    plot(profiles, args.out)
    print(f"wrote rq1_profile.json and {args.out}")


if __name__ == "__main__":
    main()
