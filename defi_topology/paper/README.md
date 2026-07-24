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

## Submission metadata
Submission forms want a *plain-text* abstract, and their PDF auto-extractors mangle
it — SSRN's flattens every em dash to a bare hyphen with no spaces, turning
"survivor-biased — reconstructing" into "survivor-biased-reconstructing". Paste
`abstract.txt` over whatever the form extracted. Regenerate it after any edit to the
abstract so the two cannot drift apart:

```
python abstract_txt.py -o abstract.txt
```

Keywords printed in the manuscript: Decentralised finance; Higher-order networks;
Persistent homology; Survivorship bias; Automated market makers. Submission forms
allow more than the paper prints — worth also entering **Topological data analysis**
(the umbrella term readers browse by) and **Stablecoins** (the paper's whole subject,
absent from the printed list). Add them to the `\twocolumn[...]` Keywords line in
`main.tex` too if the PDF is ever recompiled before upload.

## Before posting
- Author name/email and the three arXiv reference author lists are filled in.
- **Venue:** SSRN or Zenodo need no endorsement (recommended path). arXiv q-fin
  requires an endorsement for a first-time submitter — an upgrade path, not a
  blocker.
- **DOI:** the manuscript has none and no prior posted version, so leave any
  "publication details / DOI" field on the submission form blank — SSRN mints
  `10.2139/ssrn.<id>` on acceptance. A Zenodo DOI on the *repository* (code + data,
  versioned) would be a better long-term target for the Reproducibility section than
  the bare GitHub URL it currently cites.
- **Affiliation:** undergraduate student, Hofstra University — not a departmental
  appointment.
