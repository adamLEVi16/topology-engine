#!/usr/bin/env python3
"""Inline the TeamBuy demo into a single self-contained HTML file.

The multi-file source in this directory is the thing you edit. This script
flattens it — fonts, stylesheet and script all embedded — so the page can be
opened from disk or published anywhere that disallows external requests.

    python3 teambuy/build.py        ->  teambuy/dist/teambuy-demo.html
"""
import pathlib
import re

HERE = pathlib.Path(__file__).parent
DIST = HERE / "dist"


def build() -> pathlib.Path:
    html = (HERE / "index.html").read_text(encoding="utf-8")
    fonts = (HERE / "assets" / "fonts.css").read_text(encoding="utf-8")
    styles = (HERE / "styles.css").read_text(encoding="utf-8")
    script = (HERE / "app.js").read_text(encoding="utf-8")

    html = html.replace(
        '<link rel="stylesheet" href="assets/fonts.css" />\n'
        '<link rel="stylesheet" href="styles.css" />',
        "<style>\n" + fonts + "\n" + styles + "\n</style>",
    )
    html = html.replace(
        '<script src="app.js"></script>',
        "<script>\n" + script + "\n</script>",
    )

    for leftover in re.findall(r'<(?:link|script)[^>]*(?:href|src)="(?!https?:)[^"]+"', html):
        raise SystemExit(f"build: local asset was not inlined -> {leftover}")

    DIST.mkdir(exist_ok=True)
    out = DIST / "teambuy-demo.html"
    out.write_text(html, encoding="utf-8")
    return out


if __name__ == "__main__":
    path = build()
    print(f"{path}  ({path.stat().st_size / 1024:.0f} KB)")
