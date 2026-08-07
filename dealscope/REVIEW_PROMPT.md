# Code review request — `dealscope`

Copy everything below the line into another AI, alongside access to the repo.

---

You are doing a code review of a single Python project. Be direct and specific.
I want to find real problems, not receive praise.

## Scope — read this first

**Review only the `dealscope/` directory.** The repository it lives in also
contains an unrelated project called `topology_engine` (a topological data
analysis library, under `src/topology_engine/` at the repo root). That project
is **out of scope**. Do not read it, do not review it, do not comment on it, and
do not flag the fact that two unrelated projects share a repository — that is a
deliberate choice, already known.

Everything you review is under `dealscope/`:

```
dealscope/
  pyproject.toml
  README.md
  src/dealscope/
    __init__.py  __main__.py  analyzer.py  browser.py  cli.py  config.py
    discovery.py  fetch.py  models.py  narrate.py  scoring.py  web.py
    extract/     commerce.py contact.py content.py hiring.py identity.py
                 people.py structured.py tech.py
    sources/     fmcsa.py            (public records, not the company's site)
    render/      html.py markdown.py
    templates/   *.html  (Jinja2)
  tests/         8 files, ~1,580 lines, 121 tests
```

~6,200 lines of source, ~1,580 of tests. Python 3.10+. Dependencies:
`requests`, `beautifulsoup4`, `lxml`, `Jinja2`; optionally `playwright`.

## What the project does

`dealscope` reads a company's public website — and, optionally, public
records — and produces a short brief for someone considering **buying that
business**. Domain in, brief out:

1. `fetch.py` — polite HTTP: robots.txt, `Crawl-delay`, `Retry-After`,
   per-host rate limiting, disk cache with pruning, byte caps, and a `post()`
   used by records lookups.
2. `browser.py` — optional Playwright fallback, used only when a page comes
   back too thin to be the whole page. Must degrade silently when absent.
3. `discovery.py` — decides which pages matter (pricing, about, team, careers,
   customers, legal) by classifying links, reading sitemaps, applying
   platform-specific path knowledge, and guessing conventional paths. Returns
   ranked candidates per role.
4. `analyzer.py` — orchestrates: fetch homepage, plan candidates, fetch with
   fallback across candidates and rescue passes, optionally re-render, run
   extractors, optionally hit FMCSA, score, narrate.
5. `extract/*` — regex and BeautifulSoup heuristics producing facts plus
   `Evidence` records (field, value, source URL, method, confidence).
6. `sources/fmcsa.py` — matches a company to a federal motor-carrier record
   and pulls fleet size, driver count, safety and status data.
7. `scoring.py` — maturity / momentum / transparency / evidence-coverage
   scores, risk flags, unknowns, and diligence questions. Business-type aware:
   some measures are marked `assessable=False` rather than scored low.
8. `narrate.py` — deterministic prose; optionally hands a *fact sheet* (never
   raw pages) to Claude for a rewrite.
9. `render/`, `templates/` — text, Markdown, JSON, HTML output.
10. `web.py` — stdlib HTTP server, background jobs, self-refreshing progress page.

## Design principles it is meant to honour

Judge the code against these, and tell me where it fails them:

1. **Every claim carries a source.** Any fact reaching a brief must have an
   `Evidence` record with a URL, extraction method, and confidence.
2. **Absence is reported as absence, never as a verdict.** "No pricing found"
   is a gap in the brief, not a judgement on the company. Where robots.txt
   blocks a page, the site is client-rendered, or a records match is too weak,
   the brief must say so.
3. **Never invent.** The deterministic narrator must be structurally incapable
   of stating something the extractors did not observe.
4. **Politeness is not optional.** There is deliberately no flag to disable
   robots.txt compliance, and no attempt to evade any block.
5. **The scores matter less than the questions.** Uncertainty must be visible.

## Where I most want your attention

Ordered by how much I care:

1. **Correctness of the heuristics.** `extract/` is regex-heavy. Hunt for
   patterns that over-match, match across line boundaries, match mid-token, or
   attribute third-party content to the company being analyzed. Bugs of exactly
   these kinds have already shipped and been fixed: a landscaping company
   classified as "developer tools" (`api` matched inside `landscaping`);
   `776 people` extracted from `"33,776 people"`; a tech publication's articles
   about *other* companies read as its own funding history. **Assume more
   exist — the last two are still unfixed at the time of writing.**
2. **Self-contradiction.** The narrative is assembled from independent
   fragments, so it can assert "no pricing found" and then list prices two
   sentences later. This is a known live defect. Find every path where two
   sections of a brief can disagree.
3. **Entity matching in `sources/fmcsa.py`.** Attaching the wrong carrier's
   fleet size and crash history to a business would be the worst failure this
   tool can produce. Scrutinise the thresholds, the runner-up margin rule, and
   the name normalisation. Can a wrong match get through? Can a correct one be
   rejected too eagerly?
4. **Scoring soundness.** Weights in `scoring.py` are hand-picked. Are they
   internally consistent? Can a score mislead rather than merely be wrong? Is
   `assessable=False` honoured everywhere it should be, including all renderers?
5. **Robustness.** `analyze()` promises never to raise on network or parsing
   failure. Verify that. Check `browser.py` degradation paths, and `web.py`
   threading — the job store is mutated from both request and worker threads.
6. **Security.** Templates render scraped third-party content; check escaping is
   complete. The web server accepts a user-supplied domain — check for **SSRF**
   (can it be pointed at `localhost`, cloud metadata endpoints, or private IP
   ranges?), path traversal in cache keys, and resource exhaustion.
7. **Test quality.** Do the tests pin behaviour, or restate the implementation?
   Where is coverage thin? Which of the known bugs above would the current
   suite have caught?

## What not to spend time on

- Style, formatting, import order, type-annotation completeness. Skip unless it
  causes a real defect.
- Suggestions to adopt a web framework, an async HTTP client, an ORM, or a
  plugin architecture. Dependency-light and stdlib-first is deliberate.
- The choice of regex/heuristics over an LLM for extraction. Determinism and
  auditability are the point.
- Praise. If something is fine, say nothing about it.

## Output I want

1. **Findings, most severe first.** For each: file and line, what is wrong, a
   concrete input that triggers it, and the consequence for a reader of the
   brief. Distinguish *confirmed* (you traced the code path) from *suspected*.
2. **A short list of the highest-leverage fixes**, in the order you would do
   them, with a rough size for each.
3. **One honest paragraph**: does this codebase do what it claims, and would
   you trust a brief it produced enough to act on?

Do not fix anything. Report only.
