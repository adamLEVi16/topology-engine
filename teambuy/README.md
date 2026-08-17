# TeamBuy — demo site

A static marketing/demo site for TeamBuy: a marketplace that pairs an experienced
operator (active partner) with capital (silent partner) into one credible buyer for
Main Street businesses priced $1M–$6M.

This folder is self-contained and unrelated to `topology_engine`. It has no build
dependencies and no runtime dependencies.

## Files

| Path | What it is |
| --- | --- |
| `index.html` | Page markup |
| `styles.css` | Design tokens and all styling (light + dark) |
| `app.js` | The buyer-team board — profiles, pairing math, fit checks |
| `assets/fonts.css` | Bricolage Grotesque, Public Sans and Courier Prime, embedded as base64 woff2 |
| `build.py` | Flattens the above into one self-contained HTML file |
| `dist/teambuy-demo.html` | Build output — opens from disk, no network needed |

## Run it

Open `index.html` directly, or serve the folder:

```bash
python3 -m http.server -d teambuy 8000   # then visit http://localhost:8000
```

## Build the single-file version

```bash
python3 teambuy/build.py     # -> teambuy/dist/teambuy-demo.html
```

The build fails loudly if any local asset is left un-inlined, so the output is always
safe to open offline or host somewhere that blocks external requests.

## The capital stack

The `#math` section is the centre of the argument: almost all of a Main Street deal is
bank debt, and that part is not the obstacle. Two sliders (purchase price, operator's own
cash) drive one stacked bar, annotated with a bracket over the equity injection — the only
band that ever blocks a capable operator.

Chart colours are a separate, validated categorical set (not the brand canary, which
fails the lightness band and contrast as a data colour). Both light and dark steps pass
the six checks — lightness band, chroma floor, CVD separation, normal-vision floor and
contrast — with a hover tooltip, a legend carrying exact values, and a table view.

## The board

`app.js` holds five operator profiles and five capital profiles. Selecting one of each
computes the combined equity injection and runs four checks: sector overlap, geography,
control expectations (a board seat against an operator who wants full control is a
blocking conflict), and financing headroom against SBA 7(a) terms — 10% minimum equity
injection, $5M loan cap. Failing pairs are meant to fail visibly; the demo is more
convincing when it shows friction than when everything matches.

To change the roster, edit the `OPERATORS` and `INVESTORS` arrays at the top of
`app.js`. Financing assumptions are the `SBA_DOWN`, `SBA_LOAN_CAP` and `FOCUS_MAX`
constants below them.

## Design notes

Palette and type come from the paperwork of the trades this targets — an NCR triplicate
work order: ballpoint ink, cool drafting paper, carbon-copy canary, rubber-stamp red.
Canary is reserved for one idea only — two halves becoming a single buyer — so it means
something wherever it appears. Courier Prime carries the form-field labels, Public Sans
the running text, Bricolage Grotesque the headlines.

## Disclaimer

Every profile, figure and fee on the page is an illustrative placeholder. Nothing
represents a real person, listing or offer, and the SBA references are illustrative,
not advice.
