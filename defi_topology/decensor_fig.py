#!/usr/bin/env python3
"""
Central v2 figure: the survivor-only reconstruction fabricates both the level and the
trend of the higher-order fraction. Reads decensor_series.json (from decensor.py).

  python decensor_fig.py   ->  figs/decensor.png
"""
import datetime, json, os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

DEPEG = datetime.date(2023, 3, 11)


def main():
    rows = json.load(open("decensor_series.json"))
    D = [datetime.date.fromisoformat(r["date"]) for r in rows]
    full_b1 = [r["full"]["essB1"] for r in rows]
    surv_b1 = [r["survivor"]["essB1"] for r in rows]
    full_hf = [r["full"]["ho_fraction"] for r in rows]
    surv_hf = [r["survivor"]["ho_fraction"] for r in rows]
    svp = [100 * r["true_survivorship"] for r in rows]

    fig, ax = plt.subplots(2, 1, figsize=(10, 7.5), sharex=True)

    ax[0].plot(D, full_b1, "o-", color="#1f77b4", ms=3, lw=1.6,
               label="de-censored (full historical universe)")
    ax[0].plot(D, surv_b1, "s-", color="#ff7f0e", ms=3, lw=1.6,
               label="survivor-only (what the paper could see)")
    ax[0].set_ylabel("essential $B_1$  (independent loops)")
    ax[0].legend(fontsize=9, loc="upper left")
    ax[0].set_title("Survivor-only reconstruction sees ~1/10 of the loop structure, "
                    "and fabricates a trend in the higher-order fraction", fontsize=11)

    ax[1].plot(D, full_hf, "o-", color="#2ca02c", ms=3, lw=1.8,
               label="de-censored higher-order fraction (real: ~constant, minority)")
    ax[1].plot(D, surv_hf, "s-", color="#d62728", ms=3, lw=1.8,
               label="survivor higher-order fraction (artifactual decline)")
    ax[1].axhline(0.5, color="gray", ls=":", lw=1)
    ax[1].set_ylabel("higher-order fraction\n(gap / skeleton cycle rank)")
    ax[1].set_ylim(0, 0.85)
    ax[1].legend(fontsize=9, loc="center left")

    axr = ax[1].twinx()
    axr.plot(D, svp, color="#7f7f7f", ls="--", lw=1, alpha=.7)
    axr.set_ylabel("true survivorship (%)", color="#7f7f7f", fontsize=9)
    axr.tick_params(axis="y", labelcolor="#7f7f7f")
    axr.set_ylim(0, 100)

    for a in ax:
        a.axvline(DEPEG, color="crimson", ls="--", lw=1)
        a.grid(alpha=.25)
    ax[0].annotate("USDC depeg", (DEPEG, ax[0].get_ylim()[1]), fontsize=8,
                   color="crimson", ha="center", va="top")

    os.makedirs("figs", exist_ok=True)
    plt.tight_layout()
    plt.savefig("figs/decensor.png", dpi=160, bbox_inches="tight")
    plt.close()
    print("wrote figs/decensor.png")

    # the smoking gun, as a number: survivor HOfrac tracks the survivorship rate,
    # converging to the (constant) de-censored value as survivorship -> 1.
    import statistics as S
    def pearson(x, y):
        mx, my = S.mean(x), S.mean(y)
        num = sum((a - mx) * (b - my) for a, b in zip(x, y))
        dx = sum((a - mx) ** 2 for a in x) ** .5
        dy = sum((b - my) ** 2 for b in y) ** .5
        return num / (dx * dy)
    print(f"corr(survivor HOfrac, survivorship%) = {pearson(surv_hf, svp):.2f}  "
          f"(negative = artifact: as more pools survive, the survivor fraction falls to truth)")
    print(f"de-censored HOfrac: mean {S.mean(full_hf):.3f}, sd {S.pstdev(full_hf):.3f}  (flat)")
    print(f"survivor  HOfrac: {surv_hf[0]:.2f} -> {surv_hf[-1]:.2f}  (spurious decline)")


if __name__ == "__main__":
    main()
