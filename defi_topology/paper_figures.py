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

Both are authored titleless at final printed width -- the claim lives in the
LaTeX caption, per figstyle.py.

Run: python paper_figures.py
"""
import datetime, glob, json, os

import matplotlib.dates as mdates
import matplotlib.pyplot as plt

import decensor as D
import figstyle as F

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

    fig, ax = plt.subplots(figsize=(F.FULLWIDTH, 3.3))
    # the band between the two conventions is the whole point: same data, and the
    # majority line runs right through the middle of it.
    ax.fill_between(D_, vtx, res, color=F.GREY, alpha=.13, lw=0,
                    label="span of a single unreported modelling choice")
    ax.axhline(0.5, color="#4D4D4D", ls=(0, (5, 3)), lw=0.9)
    ax.plot(D_, res, "s-", color=F.DARKRED,
            label="resolved (3CRV $\\rightarrow$ base assets): a declining majority")
    ax.plot(D_, vtx, "o-", color=F.GREEN,
            label="lp_vertex (3CRV as its own vertex): a flat minority")
    ax.text(D_[0], 0.515, "majority higher-order", fontsize=7.2, color=F.DARKRED, va="bottom")
    ax.text(D_[0], 0.485, "minority higher-order", fontsize=7.2, color=F.GREEN, va="top")
    for ev, lab, ha in [(DEPEG, "USDC depeg", "right"), (CURVE, "Curve exploit", "left")]:
        F.event_marker(ax, ev, lab, color=F.PURPLE, ha=ha)
    ax.set_ylim(0.15, 0.95)
    ax.set_ylabel("higher-order fraction\n(gap / skeleton cycle rank)")
    ax.legend(loc="upper right", ncol=1)
    F.grid(ax)
    fig.savefig("figs/representation.png")
    plt.close(fig)
    print(f"wrote figs/representation.png  (lp_vertex mean {sum(vtx)/len(vtx):.2f}, "
          f"resolved {res[0]:.2f}->{res[-1]:.2f})")


# ============================================================ figure 2
def fig_curve_artifact(M):
    dates = sorted(M)
    window = [d for d in dates if datetime.date(2023, 7, 1) <= d <= datetime.date(2023, 8, 25)]
    pre_d, mid_d, post_d = datetime.date(2023, 7, 30), datetime.date(2023, 8, 2), datetime.date(2023, 8, 22)
    pre, mid, post = tvl_map(M[pre_d]), tvl_map(M[mid_d]), tvl_map(M[post_d])
    # project-qualified: DeFiLlama lists the same Curve pool again under Convex, so
    # the bare symbol is not unique and would give a legend with repeated entries.
    sym = {p["pool"]: f'{p.get("project", "?").split("-")[0]} {p.get("symbol", "?")}'
           for p in load_uni(M[pre_d])}

    # biggest transient dippers on 08-02
    dippers = [pid for pid in set(pre) & set(mid) & set(post)
               if pre[pid] > 1e5 and post[pid] > 1e5 and mid[pid] < 0.5 * min(pre[pid], post[pid])]
    n_dip_rows = len(dippers)
    dippers = all_dippers = sorted(dippers, key=lambda p: -pre[p])
    # One underlying Curve pool appears as several registry rows (Convex re-lists it), so
    # plotting rows directly draws identical series on top of each other. Keep the largest
    # row per symbol -- distinct *pools* -- and report the row count in the caption.
    seen, distinct = set(), []
    for pid in dippers:
        s = sym.get(pid, "?").split(" ", 1)[-1]
        if s not in seen:
            seen.add(s)
            distinct.append(pid)
    dippers = distinct[:4]
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

    fig, ax = plt.subplots(2, 1, figsize=(F.FULLWIDTH, 4.9), sharex=True,
                           gridspec_kw={"hspace": 0.16})
    palette = [F.BLUE, F.DARKRED, F.GREEN, F.PURPLE, F.YELLOW]
    for pid, col in zip(dippers, palette):
        ys = [wmaps[d].get(pid, 0) / 1e6 for d in window]
        ax[0].plot(window, ys, "o-", color=col, label=sym.get(pid, "?")[:18])
    # shade the single corrupted crawl so the eye lands on it first
    ax[0].axvspan(mid_d - datetime.timedelta(days=1), mid_d + datetime.timedelta(days=1),
                  color=F.RED, alpha=.13, lw=0, zorder=0)
    ax[0].set_ylabel("pool TVL (\\$M)")
    # headroom above the 625M peak so the legend sits in clear space, not on the data.
    # The "N transiently dipped rows" fact lives in the caption, not in a legend title.
    ax[0].set_ylim(-30, 900)
    ax[0].set_yticks([0, 200, 400, 600, 800])
    ax[0].legend(ncol=2, loc="upper left", columnspacing=1.2)
    F.grid(ax[0])
    F.panel(ax[0], "a")

    ax[1].axvspan(mid_d - datetime.timedelta(days=1), mid_d + datetime.timedelta(days=1),
                  color=F.RED, alpha=.13, lw=0, zorder=0)
    ax[1].plot(window, raw, "o-", color=F.DARKRED,
               label="raw crawl (spurious spike)")
    ax[1].plot(window, rep, "s--", color=F.GREEN,
               label="after transient-dip repair (inert)")
    ax[1].set_ylabel("essential $B_1$ (loops)")
    ax[1].set_xlabel("2023")
    ax[1].set_ylim(38, 58)
    ax[1].legend(loc="lower left", ncol=2)
    F.grid(ax[1])
    F.panel(ax[1], "b")
    ax[1].xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO, interval=2))
    ax[1].xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))

    for a in ax:
        F.event_marker(a, CURVE, None, color=F.PURPLE)
    F.event_marker(ax[0], CURVE, "Curve/Vyper exploit", color=F.PURPLE)

    fig.savefig("figs/curve_artifact.png")
    plt.close(fig)
    print(f"wrote figs/curve_artifact.png  (essB1 raw {raw} -> repaired {rep})")
    # the caption quotes these, so print them: rows dipped, distinct pools, FRAX share.
    frax = sum(1 for p in all_dippers if "FRAX" in sym.get(p, ""))
    print(f"  {n_dip_rows} transiently dipped registry rows, {len(distinct)} distinct pools, "
          f"{frax} rows FRAX-symboled")
    for pid in dippers:
        print(f"    {sym.get(pid,'?'):26s} {pre[pid]/1e6:7.1f} -> {mid[pid]/1e6:6.1f} -> "
              f"{post[pid]/1e6:7.1f}  (recovery {post[pid]/pre[pid]:.2f}x)")


def main():
    F.apply()
    os.makedirs("figs", exist_ok=True)
    M = snap_index()
    fig_representation(M)
    fig_curve_artifact(M)


if __name__ == "__main__":
    main()
