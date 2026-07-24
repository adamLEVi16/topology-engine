#!/usr/bin/env python3
"""
Shared journal-figure style for the manuscript figures.

Conventions taken from the target journal layout (Springer / J. Banking and Financial
Technology):

  * No title baked into the image. In a journal the figure's claim lives in the caption
    ("Fig. 1 ..."), not inside the axes -- a title in both places is duplicated, and a
    title only in the image is uncitable. Every figure here is authored titleless.
  * Panels are labelled (a)/(b) in the top-left, referenced from the caption.
  * Figures are authored at their *final printed size* (~7in = full two-column width), so
    \\includegraphics does no scaling and in-figure type stays at its intended point size.
    Never author at 10in and let LaTeX shrink it -- that is what makes labels unreadable.
  * Restrained, colourblind-safe palette (Paul Tol); light y-grid only; no top/right
    spines; frameless legends. Filled areas under/between curves, which is the one
    genuinely useful stylistic element of the reference paper's charts.

Import for side effects, then use the palette:

    import figstyle as F
    F.apply()
    ax.plot(x, y, color=F.BLUE)
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# --- Paul Tol's "bright" qualitative scheme: distinguishable in colour, in greyscale,
#     and under the common forms of colour-vision deficiency.
BLUE   = "#4477AA"
RED    = "#EE6677"
GREEN  = "#228833"
YELLOW = "#CCBB44"
CYAN   = "#66CCEE"
PURPLE = "#AA3377"
GREY   = "#8C8C8C"
DARKRED = "#BB2222"

# full width of the two-column text block, in inches
FULLWIDTH = 7.0
COLWIDTH = 3.35


def apply():
    plt.rcParams.update({
        "figure.dpi": 160,
        "savefig.dpi": 400,             # print-quality raster
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.02,
        "font.family": "sans-serif",
        "font.sans-serif": ["DejaVu Sans"],
        "font.size": 8.5,
        "axes.titlesize": 9,
        "axes.labelsize": 8.5,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "legend.fontsize": 7.8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.linewidth": 0.7,
        "axes.edgecolor": "#4D4D4D",
        "axes.labelcolor": "#1A1A1A",
        "text.color": "#1A1A1A",
        "xtick.color": "#4D4D4D",
        "ytick.color": "#4D4D4D",
        "xtick.major.width": 0.7,
        "ytick.major.width": 0.7,
        "xtick.major.size": 3,
        "ytick.major.size": 3,
        "grid.color": "#CCCCCC",
        "grid.linewidth": 0.5,
        "grid.alpha": 0.7,
        "legend.frameon": False,
        "legend.handlelength": 1.8,
        "legend.borderaxespad": 0.4,
        "lines.linewidth": 1.4,
        "lines.markersize": 3.2,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
    })


def grid(ax, axis="y"):
    """Light horizontal rules behind the data -- the journal-chart default."""
    ax.grid(axis=axis, zorder=0)
    ax.set_axisbelow(True)


def panel(ax, letter, dx=-0.055, dy=1.02):
    """(a)/(b) panel label in the corner, for reference from the caption."""
    ax.text(dx, dy, f"({letter})", transform=ax.transAxes,
            fontsize=9.5, fontweight="bold", va="bottom", ha="left")


def event_marker(ax, when, label=None, color=GREY, ha="center"):
    """Dotted vertical rule for an event date. The label sits *above* the top spine, so
    it can never collide with the data or the legend. For two events close together,
    pass ha="right" on the earlier and ha="left" on the later to pull them apart."""
    ax.axvline(when, color=color, ls=(0, (3, 2)), lw=0.9, zorder=1)
    if label:
        pad = {"right": " ", "left": " ", "center": ""}[ha]
        text = pad + label + pad
        ax.annotate(text, xy=(when, 1.012), xycoords=("data", "axes fraction"),
                    fontsize=7.5, color=color, ha=ha, va="bottom")
