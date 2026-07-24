# Preprint source

`main.tex` is a self-contained, arXiv-ready LaTeX manuscript (only standard
packages: geometry, amsmath, natbib, graphicx, booktabs, hyperref, xcolor,
caption). Its three figures are `decensor.png`, `representation.png`, and
`curve_artifact.png`. `main.pdf` is the compiled copy.

## Compile
- **Overleaf** (easiest): upload `main.tex` + the three `.png` files, recompile.
- **Local**: `pdflatex main.tex && pdflatex main.tex` (twice, for cross-refs).

Regenerate the figures from data with `python decensor_fig.py` (Fig 1) and
`python paper_figures.py` (Figs 2–3) in the parent directory.

## Before posting
- Author name/email and the three arXiv reference author lists are filled in.
- **Venue:** SSRN or Zenodo need no endorsement (recommended path). arXiv q-fin
  requires an endorsement for a first-time submitter — an upgrade path, not a
  blocker.
