# dealscope

**Point it at a company's website. Get back a short brief written for someone thinking about buying the business.**

```
$ dealscope analyze kettlewind.com
```

```
────────────────────────────────────────────────────────────────────────
Kettlewind — Software subscription · self-serve sales · ~18 people · publishing regularly
────────────────────────────────────────────────────────────────────────

Kettlewind operates at kettlewind.com, presenting itself in SaaS / software and
healthcare. The site leads with "Scheduling that clinics actually stick with".
It claims to have been founded in 2016.

Revenue appears to come from software subscriptions (confidence 81% on public
signals). Published prices include £29 per month, £79 per month, and £249 per
month. Plans are named Starter, Practice, and Enterprise. On the evidence of its
calls to action, buyers can sign up without talking to anyone.

Headcount looks like ~18 (stated on the site); leadership is named publicly —
Priya Raman (Chief Executive Officer); 3 open roles are advertised across
Engineering, Sales, and Design; the blog is publishing regularly.

Nothing here speaks to revenue, margins, churn, or owner dependency — none of
that is publicly observable.

SCORES
  Maturity           ███████████████·····    76/100  strong
  Momentum           █████████████·······    67/100  established
  Transparency       ████████████████····    85/100  strong
  Evidence coverage  ███████████████████·    96/100  strong
```

…followed by risk flags, an explicit list of what a website *cannot* tell you,
and a set of questions to put to the seller.

---

## What it is, and what it isn't

It reads the pages a company publishes about itself — pricing, about, team,
careers, customers, legal — and turns them into a structured, cited brief. It is
a **research accelerator**: the twenty minutes of clicking around a site you'd do
before deciding whether a business is worth a real conversation.

It is **not** a business analyst, and it does not pretend to be one. It cannot
see revenue, margins, churn, customer concentration, or how much of the business
walks out the door with the current owner. The brief says so explicitly, every
time, in a section called *What this brief cannot tell you*.

Three design rules follow from that:

1. **Every claim carries a source.** Each fact links to the page it came from,
   with the method used (`json-ld`, `meta`, `regex`, `heuristic`) and a
   confidence value. Disagree with any of it by clicking through.
2. **Absence is reported as absence, not as a verdict.** "No pricing page found"
   is a gap in the brief, never a judgement on the company. Where the site
   blocks readers via `robots.txt` or builds its navigation in JavaScript, the
   brief says that rather than reporting an empty result as a finding.
3. **The scores are the least important output.** The questions at the end are
   the point.

## Install

```bash
cd dealscope
python -m pip install -e ".[dev]"
```

Python 3.10+. Dependencies: `requests`, `beautifulsoup4`, `lxml`, `Jinja2`.
No API keys required.

## Use

```bash
# a readable summary in the terminal
dealscope analyze acme.com

# other formats
dealscope analyze acme.com --format md   --output brief.md
dealscope analyze acme.com --format html --output brief.html
dealscope analyze acme.com --format json --output brief.json

# several at once, one file each
dealscope analyze acme.com beta.io gamma.co --format md --output ./briefs/

# local web UI — paste a domain, read the brief
dealscope serve
```

Useful flags: `--max-pages` (default 20), `--delay` (seconds between requests to
a host, default 1.0), `--timeout`, `--no-cache`, `--quiet`.

### As a library

```python
from dealscope import analyze, Config

brief = analyze("acme.com", Config(max_pages=12))

print(brief.headline)
print(brief.business_model.primary)      # saas | ecommerce | services | ...
print(brief.scores.maturity.value)       # 0-100, with .rationale
for flag in brief.risk_flags:
    print(flag.severity, flag.title)
for evidence in brief.all_evidence():
    print(evidence.field, evidence.value, evidence.source_url)
```

## What's in a brief

| Section | What it answers |
|---|---|
| Summary | What the business appears to be and how it appears to make money |
| Scorecard | Maturity, momentum, transparency — plus evidence coverage, the confidence gauge for the brief itself |
| Business model | SaaS, e-commerce, services, marketplace, media, or hardware; sales motion; published prices, plans, billing periods |
| Scale and team | Headcount signals, named leadership, locations, named customers, founding year |
| Momentum | Open roles and departments, publishing cadence, site freshness, funding or ownership mentions |
| Operations | Technology fingerprints, and platform dependencies that become migration work after a sale |
| Contact and trust | Emails, phones, addresses, socials, legal pages, compliance claims |
| Risk flags | Severity-ranked, each explaining why it matters to a buyer |
| What this cannot tell you | The structural blind spots, stated plainly |
| Questions for the seller | Tailored to the detected revenue model |
| Evidence | Every observation, with method, confidence, and source URL |

Questions adapt to the model. A SaaS business gets asked about net revenue
retention and CAC payback; an e-commerce business about AOV, supplier terms, and
blended ROAS; an agency about client concentration and how much delivery work
the owner personally does.

## Yes, this is web scraping — the polite kind

Every request:

- identifies itself with a descriptive `User-Agent`,
- fetches and honours `robots.txt`, skipping anything disallowed,
- waits a configurable delay between hits to the same host (1s by default),
- caps how many pages it reads (20) and how many bytes per page,
- is cached on disk for 24 hours, so re-running a brief costs the site nothing.

It reads only publicly served HTML. It never logs in, submits a form, solves a
challenge, or touches anything behind authentication. There is deliberately no
flag to disable `robots.txt` compliance.

## Optional: nicer prose

By default the summary is written by a deterministic generator — fully
reproducible, and structurally incapable of inventing a fact.

With `ANTHROPIC_API_KEY` set, `--llm` hands the *extracted fact sheet* (never the
raw pages) to Claude to rewrite more fluently, under instructions to use only
those facts and to state unknowns as unknown. If the call fails for any reason,
the deterministic summary stands. The brief always records which writer produced
the prose.

```bash
export ANTHROPIC_API_KEY=sk-...
dealscope analyze acme.com --llm
```

## Known limits

- **Server-rendered HTML only.** Sites that assemble navigation in the browser
  yield less. The brief flags when it detects this rather than reporting a thin
  result as a finding.
- **English-language heuristics.** Vocabulary matching is tuned for English
  sites; other languages will fall back to structured data and produce a
  sparser brief.
- **Marketing copy is marketing copy.** "Trusted by 1,200 clinics" is recorded
  as a *claim*, labelled as unverified. Same for compliance certifications.
- **No third-party data.** No WHOIS, no traffic estimates, no funding databases,
  no company registries. Everything comes from the site itself, which keeps the
  tool free and keyless but bounds what it can know.
- **Small sites score low, and that's fine.** A profitable one-person business
  with a four-page site will score "thin" on maturity. The score measures the
  website, not the company — read the evidence, not the number.

## Tests

```bash
python -m pytest
```

54 tests, all offline against synthetic fixture sites — no network required.
