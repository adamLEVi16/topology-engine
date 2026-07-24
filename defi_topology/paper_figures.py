#!/usr/bin/env python3
"""
Two v2 figures, computed directly from the archive cache:

  figs/representation.png : higher-order fraction over time under BOTH LP
      representations (full universe). The lines sit on opposite sides of the
      0.5 majority/minority line -- the "majority higher-order" claim is a
      representation choice, not a fact. (Finding 2 / Table 1, made visual.)

  figs/curve_artifact.png : the 2023-08-02 crawl glitch. Top: TVL of the biggest
      transient-dip pools cratering and fully recovering in 3 weeks (undeniably
      a data artifact). Bottom: the spurious essential-B1 spike it injects, and
      its removal by repair_transient_dips. (Finding 4, made visual.)

Run: python paper_figures.py
"""
import datetime, glob, json, os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import decensor as D

DEPEG = datetime.date(2023, 3, 11)
CURVE = datetime.date(2023, 7, 30)


def snap_index():
    m = {}
    for fn in sorted(glob.glob("archive/*.json")):
        ts = fn.split("/")[-1].replace(".json", "")
        m[datetime.date(int(ts[:4]), int(ts[4:6]), int(ts[6:8]))] = fn
    return m


def load_uni(fn):
    return [p for p in json.load(open(fn)) if D.is_universe(p)]


def tvl_map(fn):
    return {p["pool"]: (p.get("tvlUsd") or 0) for p in load_uni(fn)}


# ============================================================ figure 1
def fig_representation(M):
    dates = sorted(M)
    tvl = {d: D.universe_tvl(json.load(open(M[d]))) for d in dates}
    def flagged(d):
        i = dates.index(d)
        nb = [tvl[dates[j]] for j in (i - 1, i + 1) if 0 <= j < len(dates)]
        med = sorted(nb)[len(nb) // 2] if nb else tvl[d]
        return tvl[d] < 0.6 * med
    D_, vtx, res = [], [], []
    for d in dates:
        if flagged(d):                      # drop the corrupted 08-02 crawl
            continue
        uni = load_uni(M[d])
        D_.append(d)
        vtx.append(D.observables(uni, resolve=False)["ho_fraction"])
        res.append(D.observables(uni, resolve=True)["ho_fraction"])

    fig, ax = plt.subplots(figsize=(10, 4.6))
    ax.fill_between(D_, 0.5, 1.0, color="#d62728", alpha=.05)
    ax.fill_between(D_, 0.0, 0.5, color="#2ca02c", alpha=.05)
    ax.plot(D_, res, "s-", color="#d62728", ms=3, lw=1.8,
            label="resolved  (3CRV → base assets):  a declining MAJORITY")
    ax.plot(D_, vtx, "o-", color="#2ca02c", ms=3, lw=1.8,
            label="lp_vertex (3CRV as its own vertex):  a flat MINORITY")
    ax.axhline(0.5, color="k", ls="--", lw=1)
    ax.text(D_[0], 0.51, "majority higher-order", fontsize=8, color="#d62728", va="bottom")
    ax.text(D_[0], 0.49, "minority higher-order", fontsize=8, color="#2ca02c", va="top")
    for ev, lab in [(DEPEG, "USDC depeg"), (CURVE, "Curve exploit")]:
        ax.axvline(ev, color="gray", ls=":", lw=1)
    ax.set_ylim(0.15, 0.95)
    ax.set_ylabel("higher-order fraction\n(gap / skeleton cycle rank)")
    ax.set_title("The same de-censored universe is majority- or minority-higher-order "
                 "depending only on\nhow one LP token is represented", fontsize=11)
    ax.legend(fontsize=9, loc="center right")
    ax.grid(alpha=.25)
    plt.tight_layout()
    plt.savefig("figs/representation.png", dpi=160, bbox_inches="tight")
    plt.close()
    print(f"wrote figs/representation.png  (lp_vertex mean {sum(vtx)/len(vtx):.2f}, "
          f"resolved {res[0]:.2f}->{res[-1]:.2f})")


# ============================================================ figure 2
def fig_curve_artifact(M):
    dates = sorted(M)
    window = [d for d in dates if datetime.date(2023, 7, 1) <= d <= datetime.date(2023, 8, 25)]
    pre_d, mid_d, post_d = datetime.date(2023, 7, 30), datetime.date(2023, 8, 2), datetime.date(2023, 8, 22)
    pre, mid, post = tvl_map(M[pre_d]), tvl_map(M[mid_d]), tvl_map(M[post_d])
    sym = {p["pool"]: p.get("symbol", "?") for p in load_uni(M[pre_d])}

    # biggest transient dippers on 08-02
    dippers = [pid for pid in set(pre) & set(mid) & set(post)
               if pre[pid] > 1e5 and post[pid] > 1e5 and mid[pid] < 0.5 * min(pre[pid], post[pid])]
    dippers = sorted(dippers, key=lambda p: -pre[p])[:5]
    wmaps = {d: tvl_map(M[d]) for d in window}

    # essB1 raw vs repaired across the window
    raw, rep = [], []
    for d in window:
        i = dates.index(d)
        uni = load_uni(M[d])
        raw.append(D.observables(uni, resolve=False)["essB1"])
        pr = load_uni(M[dates[max(i - 1, 0)]]); po = load_uni(M[dates[min(i + 1, len(dates) - 1)]])
        fixed, _ = D.repair_transient_dips(uni, pr, po)
        rep.append(D.observables(fixed, resolve=False)["essB1"])

    fig, ax = plt.subplots(2, 1, figsize=(9, 7), sharex=True)
    for pid in dippers:
        ys = [wmaps[d].get(pid, 0) / 1e6 for d in window]
        ax[0].plot(window, ys, "o-", ms=4, lw=1.6, label=sym.get(pid, "?")[:18])
    ax[0].axvline(CURVE, color="crimson", ls="--", lw=1)
    ax[0].set_ylabel("pool TVL ($M)")
    ax[0].set_title("The 2023-08-02 archive crawl is corrupted: the biggest 'dippers' crater\n"
                    "and fully recover within 3 weeks — a data glitch, not a $1.3B drawdown",
                    fontsize=11)
    ax[0].legend(fontsize=8, ncol=2, title="transient-dip pools")
    ax[0].grid(alpha=.25)

    ax[1].plot(window, raw, "o-", color="#d62728", ms=5, lw=1.8,
               label="essential $B_1$, raw crawl (spurious spike)")
    ax[1].plot(window, rep, "s--", color="#2ca02c", ms=5, lw=1.8,
               label="essential $B_1$, after transient-dip repair (inert)")
    ax[1].axvline(CURVE, color="crimson", ls="--", lw=1)
    ax[1].annotate("Curve/Vyper\nexploit", (CURVE, ax[1].get_ylim()[1]), fontsize=8,
                   color="crimson", ha="center", va="top")
    ax[1].set_ylabel("essential $B_1$ (loops)")
    ax[1].set_xlabel("2023")
    ax[1].legend(fontsize=9, loc="upper left")
    ax[1].grid(alpha=.25)
    plt.tight_layout()
    plt.savefig("figs/curve_artifact.png", dpi=160, bbox_inches="tight")
    plt.close()
    print(f"wrote figs/curve_artifact.png  (essB1 raw {raw} -> repaired {rep})")


def main():
    os.makedirs("figs", exist_ok=True)
    M = snap_index()
    fig_representation(M)
    fig_curve_artifact(M)


if __name__ == "__main__":
    main()
