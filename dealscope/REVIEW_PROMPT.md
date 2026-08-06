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
    render/      html.py markdown.py
    templates/   *.html  (Jinja2)
  tests/         ~1350 lines, 102 tests
```

About 5,700 lines of source, 1,350 of tests. Python 3.10+. Dependencies:
`requests`, `beautifulsoup4`, `lxml`, `Jinja2`, and optionally `playwright`.

## What the project does

`dealscope` reads a company's public website and produces a short brief for
someone considering **buying that business**. Domain in, brief out:

1. `fetch.py` — polite HTTP: robots.txt, `Crawl-delay`, `Retry-After`,
   per-host rate limiting, disk cache, byte caps.
2. `discovery.py` — decides which pages matter (pricing, about, team, careers,
   customers, legal) by classifying links, reading sitemaps, and guessing
   conventional paths. Returns ranked candidates per role.
3. `analyzer.py` — orchestrates: fetch homepage, plan candidates, fetch with
   fallback across candidates, run extractors, score, narrate.
4. `extract/*` — regex and BeautifulSoup heuristics producing facts plus
   `Evidence` records (field, value, source URL, method, confidence).
5. `scoring.py` — maturity / momentum / transparency / evidence-coverage
   scores, risk flags, unknowns, and diligence questions.
6. `narrate.py` — deterministic prose; optionally hands a *fact sheet* (never
   raw pages) to Claude for a rewrite.
7. `render/`, `templates/` — text, Markdown, JSON, HTML output.
8. `web.py` — stdlib HTTP server with background jobs and a polling page.

## Design principles it is meant to honour

Judge the code against these, and tell me where it fails them:

1. **Every claim carries a source.** Any fact reaching a brief must have an
   `Evidence` record with a URL, extraction method, and confidence.
2. **Absence is reported as absence, never as a verdict.** "No pricing found"
   is a gap in the brief, not a judgement on the company. Where robots.txt
   blocks a page or the site is client-rendered, the brief must say so.
3. **Never invent.** The deterministic narrator must be structurally incapable
   of stating something the extractors did not observe.
4. **Politeness is not optional.** There is deliberately no flag to disable
   robots.txt compliance.
5. **The scores matter less than the questions.** Uncertainty must be visible.

## Where I most want your attention

Ordered by how much I care:

1. **Correctness of the heuristics.** `extract/` is regex-heavy. Hunt for
   patterns that over-match, match across line boundaries, match mid-token, or
   attribute third-party content to the company being analyzed. This code has
   already produced: a landscaping company classified as "developer tools"
   (`api` matched inside `landscaping`), `776 people` extracted from
   `"33,776 people"`, and a tech publication's articles about *other* companies
   read as its own funding history. Assume more of these exist.
2. **Self-contradiction.** The narrative is assembled from independent
   fragments, so it can assert "no pricing found" and then list prices. Find
   every path where two sections can disagree.
3. **Scoring soundness.** Weights in `scoring.py` are hand-picked. Are they
   internally consistent? Can a score be misleading rather than merely wrong?
   Is `assessable=False` handled everywhere it should be?
4. **Robustness.** `analyze()` promises never to raise on network or parsing
   failure. Verify that. Look at `browser.py` degradation paths and `web.py`
   threading — the job store is mutated from request threads and worker threads.
5. **Security.** Templates render scraped third-party content; check escaping
   is complete. The web server accepts a user-supplied domain — check for SSRF
   (can it be pointed at `localhost`, cloud metadata endpoints, or internal
   IPs?), path traversal in the cache key, and resource exhaustion.
6. **Test quality.** Do the tests actually pin behaviour, or do they restate
   the implementation? Where is coverage thin? Which of the bugs listed above
   would the current suite have caught?

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
