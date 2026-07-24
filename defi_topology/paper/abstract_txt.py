#!/usr/bin/env python3
"""
Emit the abstract as plain text for preprint submission forms (SSRN, Zenodo, arXiv).

Those forms all want a plain-text abstract, and their PDF auto-extractors mangle it:
SSRN's flattens every em dash to a bare hyphen with no spaces, so "survivor-biased --
reconstructing" comes out as "survivor-biased-reconstructing" and reads as a typo.
Paste this file's output over whatever the form extracted.

Generated from main.tex so it cannot drift out of sync with the compiled PDF.

    python abstract_txt.py            # print
    python abstract_txt.py -o abstract.txt
"""
import argparse
import re

START = "\\noindent{\\small\nA multi-asset"
END = "\\par}\n\n\\vspace{0.9em}"

# LaTeX -> plain text. Order matters: strip markup commands before unescaping.
RULES = [
    (r"%.*?\n", " "),                       # comments
    (r"\\num\{([^}]*)\}", r"\1"),
    (r"\\SI\{([^}]*)\}\{\\percent\}", r"\1%"),
    (r"\\SI\{([^}]*)\}\{([^}]*)\}", r"\1 \2"),
    (r"\\emph\{([^}]*)\}", r"\1"),
    (r"\\textbf\{([^}]*)\}", r"\1"),
    (r"\$\\sim\$", "~"),
    (r"\$\\\{\$", "{"),
    (r"\$\\\}\$", "}"),
    (r"\\,", " "),
    (r"\\ ", " "),                          # \ after e.g. / vs.
    (r"--", "\u2013"),                      # en dash
    (r"\\%", "%"),
    (r"\\&", "&"),
]


def extract(tex):
    body = tex[tex.index(START):tex.index(END)].replace("\\noindent{\\small\n", "")
    for pattern, repl in RULES:
        body = re.sub(pattern, repl, body)
    if "\\" in body:
        raise SystemExit(f"unconverted LaTeX left in abstract: {body[body.index(chr(92)):][:60]!r}")
    return " ".join(body.split())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", help="write here instead of stdout")
    ap.add_argument("--tex", default="main.tex")
    a = ap.parse_args()
    text = extract(open(a.tex, encoding="utf-8").read())
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"wrote {a.out}  ({len(text.split())} words, {len(text)} chars)")
    else:
        print(text)


if __name__ == "__main__":
    main()
