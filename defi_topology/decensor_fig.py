#!/usr/bin/env python3
"""
Central v2 figure: the survivor-only reconstruction fabricates both the level and the
trend of the higher-order fraction. Reads decensor_series.json (from decensor.py).

  python decensor_fig.py   ->  figs/decensor.png

Authored titleless at final printed width -- the claim lives in the LaTeX caption.
"""
import datetime, json, os
import statistics as S

import matplotlib.pyplot as plt

import figstyle as F

DEPEG = datetime.date(2023, 3, 11)


def pearson(x, y):
    mx, my = S.mean(x), S.mean(y)
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    dx = sum((a - mx) ** 2 for a in x) ** .5
    dy = sum((b - my) ** 2 for b in y) ** .5
    return num / (dx * dy)


def main():
    F.apply()
    with open("decensor_series.json") as fh:
        rows = json.load(fh)
    D = [datetime.date.fromisoformat(r["date"]) for r in rows]
    full_b1 = [r["full"]["essB1"] for r in rows]
    surv_b1 = [r["survivor"]["essB1"] for r in rows]
    full_hf = [r["full"]["ho_fraction"] for r in rows]
    surv_hf = [r["survivor"]["ho_fraction"] for r in rows]
    svp = [100 * r["true_survivorship"] for r in rows]

    fig, ax = plt.subplots(2, 1, figsize=(F.FULLWIDTH, 5.0), sharex=True,
                           gridspec_kw={"hspace": 0.16})

    # ---------------------------------------------------------------- (a) loop counts
    # the shaded wedge between the two lines IS the finding: everything a survivor-only
    # study cannot see.
    ax[0].fill_between(D, surv_b1, full_b1, color=F.BLUE, alpha=0.13, lw=0,
                       label="loops invisible to survivor-only reconstruction")
    ax[0].plot(D, full_b1, "o-", color=F.BLUE, label="de-censored (full historical universe)")
    ax[0].plot(D, surv_b1, "s-", color=F.DARKRED, label="survivor-only (today's registry, filtered back)")
    ax[0].set_ylabel("essential $B_1$\n(independent loops)")
    ax[0].set_ylim(0, 80)
    ax[0].legend(loc="upper left", ncol=1)
    F.grid(ax[0])
    F.panel(ax[0], "a")

    # ---------------------------------------------------------------- (b) the fraction
    axr = ax[1].twinx()
    axr.fill_between(D, 0, svp, color=F.GREY, alpha=0.10, lw=0, zorder=0)
    axr.plot(D, svp, color=F.GREY, ls=(0, (4, 2)), lw=1.0, zorder=1)
    axr.set_ylabel("true survivorship (%)", color=F.GREY)
    axr.tick_params(axis="y", labelcolor=F.GREY)
    axr.set_ylim(0, 100)
    axr.spines["right"].set_visible(True)
    axr.spines["right"].set_color("#CCCCCC")
    axr.spines["top"].set_visible(False)

    ax[1].set_zorder(axr.get_zorder() + 1)
    ax[1].patch.set_visible(False)
    ax[1].axhline(0.5, color="#999999", ls=":", lw=0.9, zorder=1)
    ax[1].plot(D, full_hf, "o-", color=F.GREEN, label="de-censored (flat minority)")
    ax[1].plot(D, surv_hf, "s-", color=F.DARKRED, label="survivor-only (artifactual decline)")
    ax[1].set_ylabel("higher-order fraction\n(gap / skeleton cycle rank)")
    ax[1].set_ylim(0, 0.85)
    ax[1].legend(loc="upper right", ncol=1)
    F.grid(ax[1])
    F.panel(ax[1], "b")
    ax[1].annotate("survivorship rate (right axis)", xy=(D[2], 0.115),
                   fontsize=7.2, color=F.GREY, ha="left", va="center")

    F.event_marker(ax[1], DEPEG, None, color=F.PURPLE)
    F.event_marker(ax[0], DEPEG, "USDC depeg", color=F.PURPLE)

    os.makedirs("figs", exist_ok=True)
    fig.savefig("figs/decensor.png")
    plt.close(fig)
    print("wrote figs/decensor.png")

    # the smoking gun, as a number: survivor HOfrac tracks the survivorship rate,
    # converging to the (constant) de-censored value as survivorship -> 1.
    print(f"corr(survivor HOfrac, survivorship%) = {pearson(surv_hf, svp):.2f}  "
          f"(negative = artifact: as more pools survive, the survivor fraction falls to truth)")
    print(f"de-censored HOfrac: mean {S.mean(full_hf):.3f}, sd {S.pstdev(full_hf):.3f}  (flat)")
    print(f"survivor  HOfrac: {surv_hf[0]:.2f} -> {surv_hf[-1]:.2f}  (spurious decline)")


if __name__ == "__main__":
    main()
