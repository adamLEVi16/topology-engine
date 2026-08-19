# dealscope

**Point it at a company's website. Get back a short brief written for someone thinking about buying the business.**

```
$ python -m dealscope analyze kettlewind.com
```

```
────────────────────────────────────────────────────────────────────────
Kettlewind — Software subscription · self-serve sales · ~18 people · publishing regularly
────────────────────────────────────────────────────────────────────────

Kettlewind operates at kettlewind.com, presenting itself in SaaS / software and
healthcare. The site leads with "Scheduling that clinics actually stick with".
It claims to have been founded in 2016.

Revenue appears to come from software subscriptions, on 6 distinct signals.
Published prices include £29 per month, £79 per month, and £249 per month. Plans
are named Starter, Practice, and Enterprise. On the evidence of its calls to
action, buyers can sign up without talking to anyone.

Headcount looks like ~18 (stated on the site); leadership is named publicly —
Priya Raman (Chief Executive Officer); 3 open roles are advertised across
Engineering, Sales, and Design; the blog is publishing regularly.

Nothing here speaks to revenue, margins, churn, or owner dependency — none of
that is publicly observable.

SCORES
  Public footprint   ███████████████·····    76/100  substantial
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

Python 3.10+. No API keys required.
Dependencies: `requests`, `beautifulsoup4`, `lxml`, `Jinja2`.

```bash
git clone https://github.com/adamLEVi16/topology-engine.git
cd topology-engine/dealscope
python -m pip install -e ".[dev]"
```

**The install step is not optional** — `dealscope` is a command that only comes
into existence once pip creates it.

### Running it

Use the module form. It works everywhere, whether or not Python's script
directory is on your PATH:

```bash
python -m dealscope analyze acme.com
python -m dealscope serve
```

The short `dealscope ...` form does the same thing, but only if pip's script
directory is on PATH — which on Windows it frequently is not.

<details>
<summary><strong>Windows / PowerShell notes</strong></summary>

Use `py` instead of `python` if `python` opens the Microsoft Store:

```powershell
py -m pip install -e ".[dev]"
py -m dealscope serve
```

`dealscope : The term 'dealscope' is not recognized` means one of two things:
you have not run the `pip install` yet, or pip's `Scripts` folder is not on
your PATH. Either way, `py -m dealscope ...` sidesteps it.

To run with no install at all, point Python at the source directory — from
inside `topology-engine\dealscope`:

```powershell
python -m pip install requests beautifulsoup4 lxml Jinja2
$env:PYTHONPATH = "src"
python -m dealscope serve
```

Check your version first — this needs 3.10 or newer:

```powershell
py --version
```
</details>

## Use

```bash
# a readable summary in the terminal
python -m dealscope analyze acme.com

# other formats
python -m dealscope analyze acme.com --format md   --output brief.md
python -m dealscope analyze acme.com --format html --output brief.html
python -m dealscope analyze acme.com --format json --output brief.json

# several at once, one file each
python -m dealscope analyze acme.com beta.io gamma.co --format md --output ./briefs/

# local web UI — paste a domain, read the brief
python -m dealscope serve
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
| Scorecard | Public footprint, momentum, transparency — plus evidence coverage, the confidence gauge for the brief itself |
| Business model | SaaS, e-commerce, services, local trade services, marketplace, media, or hardware; how many distinct signals backed the call, and the runner-up when it was close; sales motion; published prices, plans, billing periods |
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
the owner personally does; a landscaper or plumber about seasonality, crew
turnover, whether the vehicles are owned or financed, and which licences
transfer on completion.

### Local trade businesses

Landscapers, plumbers, HVAC firms, salons and clinics are a large share of the
businesses that actually change hands, and they are read differently from tech
companies:

- **They are recognised as their own revenue model** — quoted jobs and callouts,
  not subscriptions or consulting engagements.
- **Service area, opening hours, and licence/insurance claims** are extracted,
  because those are what a trade business publishes instead of a pricing page.
- **Momentum is reported as "not assessable" rather than low.** A plumber has no
  reason to blog or post jobs; scoring them on publishing cadence measures the
  yardstick, not the company.
- **Absent pricing is not flagged.** Every job is quoted, so no price list is
  normal — flagging it would be noise dressed as insight.

## Public records: the federal carrier register

A website is what a business says about itself. Filings are what it had to
declare. For a fleet business — a haulier, a FedEx ISP, a landscaper with
trucks — the filings are far better evidence, and they exist even when the
business barely has a website.

```bash
python -m dealscope analyze acme-hauling.com --fmcsa

# better, when you know the number — no name matching happens at all
python -m dealscope analyze acme-hauling.com --usdot 1554728
```

`--usdot` is the right path for a route or carrier business. A number is an
identity, so there is nothing to match and nothing to get wrong — and these
businesses very often have no website for a name to be scraped from anyway.
Three outcomes are kept apart, because they mean different things to a buyer: a
record is a record; a record SAFER reports as *inactive* means the operating
authority is dead, which is a finding; and **no record at all is not a finding**,
because vehicles under 10,001 lbs GVWR are not required to hold a USDOT number,
so a van-only fleet legitimately has none.

Without a number, this matches the company against [FMCSA SAFER](https://safer.fmcsa.dot.gov/)
and adds a section carrying **power units (trucks), driver count, operating
status, inspection and crash counts, out-of-service rate, and the MCS-150
filing date** — every field linked to the SAFER record it came from. Power
units is the closest thing to a hard measure of size this tool can obtain
anywhere: a number filed with the federal government, not a claim in marketing
copy. It also feeds the maturity score and raises real risk flags — an inactive
carrier, or an MCS-150 more than two years stale.

**Matching is the risk, not fetching.** Attaching the wrong carrier's crash
history to a business would be worse than returning nothing, so a match must
clear a name-similarity threshold *and* beat the runner-up by a margin. Where it
cannot, the brief says so and tells you what it saw:

```
_No record attached: several FMCSA records match "Swift Transportation" about
equally well (closest: 2 SWIFT TRANSPORTATION LLC, USDOT 4336702); not
attaching one without a stronger signal_
```

That is the intended outcome, not a failure — the answer is to ask the seller
for the USDOT number rather than to guess. SAFER is public, serves no
robots.txt, and needs no key; requests still go through the same rate-limited,
cached fetcher as everything else. US motor carriers only, so it is opt-in.

## Yes, this is web scraping — the polite kind

Every request:

- identifies itself with a descriptive `User-Agent`,
- fetches and honours `robots.txt`, skipping anything disallowed,
- honours `Crawl-delay` / `Request-rate` when a site asks for a slower pace, and
  **reads fewer pages rather than crawling for ten minutes** — the brief says so
  when that happens,
- honours `Retry-After` on `429` / `503` instead of guessing with backoff,
- waits a configurable delay between hits to the same host (1s by default),
- caps how many pages it reads (20) and how many bytes per page,
- is cached on disk for 24 hours and pruned by age and size, so re-running a
  brief costs the site nothing.

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
python -m dealscope analyze acme.com --llm
```

## Client-rendered sites

By default dealscope reads server HTML. Many sites build their navigation and
footer in the browser, which is why a brief can come back thin.

Install the optional browser and it renders those pages properly:

```bash
python -m pip install -e ".[js]"
playwright install chromium
```

Rendering is a **fallback, not the default path**: it fires only when a page
comes back too thin to be the whole page, or when several standard pages are
still missing after the first pass. Everything else is unchanged — `robots.txt`
is still checked before a render, and the delays still apply. If Playwright or
its browser is missing, rendering is skipped, the static HTML stands, and the
brief records that its view was partial. Turn it off entirely with `--no-js`.

If a browser is already on the machine but Playwright rejects its version, point
at it directly:

```bash
export DEALSCOPE_CHROMIUM=/path/to/chrome
```

Corporate proxies are picked up from `HTTPS_PROXY` / `NO_PROXY`.

## Known limits

- **Server-rendered HTML only, unless you install the browser** (above). The
  brief flags when it detects client-side rendering rather than reporting a thin
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

121 tests. Most run offline against synthetic fixture sites; the rendering tests
use a local HTTP server and skip when no browser is installed.
