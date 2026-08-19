# `dealscope route` — specification

**Status:** draft for discussion · **Scope:** FedEx Ground ISP/TSP and motor carriers
**Depends on:** the existing evidence model, scoring, renderers, and FMCSA source

A second input mode for brokered route listings. It reads the listing the seller
published, checks its operational claims against the federal carrier register,
and reports where the two disagree.

---

## 1. Why the existing tool doesn't reach this

dealscope analyses *a company that has a website*. A FedEx route business is *a
brokered listing of a contract*, and the two barely overlap.

Three things break at once:

- **Most ISPs have no website.** The seller is a person with twelve step vans and
  an ISP agreement, listed anonymously as "Confidential — FedEx Ground Routes,
  Central Ohio."
- **The listing venues are hard-blocked.** BizBuySell and BizQuest sit behind
  Akamai Bot Manager, which refuses even `robots.txt` to a browser user agent
  from a datacenter address.
- **The central premise inverts.** `STRUCTURAL_UNKNOWNS` states that revenue and
  customer concentration are not publicly observable — on a page whose headline
  reads `Gross Revenue: $1.4M · Cash Flow: $310K`.

That last one is not a gap in the brief. It is the brief being wrong, and it is
the same failure this project has spent four review rounds removing: asserting an
absence that isn't there.

**The fix is the input, not the fetcher.** No amount of work on the crawler
reaches a listing behind a bot wall, and attempting it would be the wrong call.
The human already has the page open.

## 2. What it is

    $ dealscope route listing.txt --usdot 1554728

    # anonymous listing, no number published yet
    $ dealscope route listing.txt

    # or paste it
    $ pbpaste | dealscope route - --usdot 1554728

Takes listing text plus an optional USDOT number. Extracts the figures the
listing publishes, pulls the carrier's federal record directly by number, and
emits a brief built around one table: what the seller claims, what the public
record shows, and where they disagree.

Reuses the `Evidence` model with its source URLs, the scoring and risk-flag
machinery, all four renderers, and `sources/fmcsa.py`. What is new is an input
path, a set of comparisons, and a question list.

### Where the listing text comes from

The human opens the listing in their own browser, on a site they are entitled to
view, under their own session, and saves or copies the page. **The tool never
fetches from a listing venue.** This belongs in the README, because it is
categorically different from working around a block — dealscope has no robots
override and refuses to evade one, and that position survives this feature intact.

## 3. Fields read from the listing

| Field | Typical form | Why it matters |
|---|---|---|
| `asking_price` | $1,250,000 | Anchors every multiple |
| `gross_revenue` | $1,400,000 | Not verifiable publicly — see §7 |
| `cash_flow_sde` | $310,000 | Implies 4.0×; benchmark is 3.0–5.0× |
| `route_count` | 7 P&D routes | Density drives labour utilisation |
| `truck_count` | 12 step vans | ↔ `power_units` |
| `employee_count` | 18 | ↔ `drivers` |
| `established` | 1998 | ↔ state registration (phase 2) |
| `location` | Central Ohio | ↔ `physical_address` |
| `terminal` | Columbus CMH | Assignment stability is a real risk |
| `contract_type` | P&D / linehaul | Different economics entirely |
| `claims_free_text` | "clean safety record" | ↔ `crashes`, `out_of_service_pct` |

Every extracted field carries the same `(field, value, source, method,
confidence)` record the website extractors produce. A field the listing does not
state is recorded as absent, never inferred.

## 4. The contradiction sheet

Extracting `Gross Revenue: $1.4M` is table stakes — the listing already says it.
The product is the comparison.

    CLAIM vs. RECORD — USDOT 1554728        SAFER · MCS-150 filed 2018-11-30
    ─────────────────────────────────────────────────────────────────────────
    truck_count       12 step vans          power_units: 7        CONTRADICTED
    employee_count    18 employees          drivers: 9            CONTRADICTED
    operating_status  "in good standing"    ACTIVE, no OOS date   CORROBORATED
    safety            "clean safety record" OOS 14.2% (avg 5.51%) CONTRADICTED
    location          Central Ohio          COLUMBUS, OH          CORROBORATED
    established       1998                  no source attached    UNVERIFIABLE
    gross_revenue     $1,400,000            no public source      UNVERIFIABLE
    ─────────────────────────────────────────────────────────────────────────
    Caveat on every row: the MCS-150 on file was filed 2018-11-30, seven years
    before this listing. Power units and driver counts are as of that filing,
    not today. A fleet that grew since would show exactly this pattern — these
    are questions to put to the seller, not conclusions about them.

Three verdicts, deliberately. Corroborated, contradicted, and unverifiable are
different things, and collapsing the third into either of the others is how a
tool starts lying.

The footer is not decoration. A stale MCS-150 is the most common innocent
explanation for a truck-count gap, and reporting the gap without it invites a
buyer to accuse a seller of something the record does not support.

## 5. Verification sources

| Claim | Checked against | Source | Status |
|---|---|---|---|
| Truck count | `power_units` | FMCSA SAFER | built |
| Employee / driver count | `drivers` | FMCSA SAFER | built |
| Operating in good standing | `operating_status`, `out_of_service_date` | FMCSA SAFER | built |
| Clean safety record | `crashes`, `inspections`, `out_of_service_pct` | FMCSA SAFER | built |
| Annual mileage | `mcs150_mileage` | FMCSA SAFER | built |
| Location / state | `physical_address` | FMCSA SAFER | built |
| Year established | Entity formation date | State SOS | phase 2 |
| Officers and ownership | Registered officers, agent | State SOS | phase 2 |
| Assets unencumbered | Liens on the fleet | UCC-1 filings | phase 2 |
| Revenue, SDE, margins | — | Settlement statements (private) | never |

The financial headline is the one thing this can never verify. The brief says so
in those words — and then verifies everything standing next to it.

## 6. Route diligence questions

`MODEL_QUESTIONS` has no route entry, so a route buyer currently falls through to
`UNIVERSAL_QUESTIONS` and misses what actually kills these deals.

1. **Will FedEx approve *you* as the incoming ISP?** The transaction is contingent
   on it and first-time buyers routinely do not know this. It goes first, above
   every financial question.
2. **Contract renewal date, and when rates were last negotiated.** Two years or
   more remaining is the preferred position.
3. **Which terminal, and how stable is the assignment?** A reassignment can
   restructure the service area under a buyer who has already closed.
4. **CSA count, geography, and route density.** Density drives labour
   utilisation, which drives the margin the listing quotes.
5. **Driver turnover over 24 months, and retention after close.** Under 20%
   annually signals strength. Drivers are the operation; vans are replaceable.
6. **Fleet by age, GVWR, mileage, owned vs financed.** Under five years is ideal.
   Deferred maintenance inflates earnings and the buyer inherits the deferral.
7. **Are drivers W-2, and does the ISP agreement require it?** A
   misclassification exposure transfers with the business.
8. **FedEx's minimum-scale requirements at this terminal.** A contractor below
   threshold is buying a forced expansion, not a going concern.

## 7. Structural risk

One counterparty provides 100% of revenue, sets the rates, assigns the territory,
and approves the buyer. That is the defining risk of a route business and it is
true of every one of them.

Which is exactly why it must **not** be a risk flag. Flags exist to say *this
business, unlike others*. A high-severity flag firing identically on every route
brief is a banner, and within three briefs a reader stops seeing it — the same
way a confidence percentage that moved with how chatty a website was stopped
carrying information.

So: a separate **Structural** section, above the flags, stating the concentration
plainly as a property of the asset class rather than an observation about this
seller. Flags stay reserved for what this listing does that others don't.

## 8. What it must never do

- **Never treat a missing SAFER record as a finding.** Vehicles under 10,001 lbs
  GVWR need no USDOT number, so a Sprinter-class P&D fleet legitimately has no
  federal record. Absence renders as absence, with the reason stated.
- **Never report a contradiction when one side is missing.** If the listing omits
  the truck count, the verdict is *unverifiable* and the row names which side is
  absent. A blank is not a zero.
- **Never compare against a stale filing silently.** Every comparison carries the
  MCS-150 date.
- **Never compute or imply a valuation.** The tool may show the arithmetic the
  listing's own figures produce; it does not endorse them and does not estimate a
  value of its own.
- **Never fetch from a listing venue.** No user-agent switching, no robots
  override. The position that made this tool worth trusting is not negotiable for
  one feature.
- **Never let a contradiction read as an accusation.** Wording is "the record does
  not support this claim," with the innocent explanation named where one exists.

## 9. Coverage limits — stated in the brief itself

- **Sub-10,001 lb fleets have no federal record.** The most important limit, and
  the one most likely to be misread as a red flag.
- **Anonymous listings give no name and no number.** Without a USDOT the brief is
  extraction only — still useful for the questions and the structural section,
  but with nothing to check against.
- **SAFER counts are self-reported** on the MCS-150, filed at most every two
  years. They are the carrier's own figures given to the government — a much
  stronger claim than a marketing page, but not an audit.
- **Revenue and SDE are unverifiable, permanently.** They live in settlement
  statements, and those arrive after an NDA.

## 10. Build order

**Phase 1 — listing input and the contradiction sheet.** Text or file input,
field extraction, SAFER comparison, three-verdict sheet, route questions,
structural section. ≈ 2–3 days. *Needs one real listing to build against.*

**Phase 2 — state registry source.** Formation date, officers, registered agent,
standing. Socrata-backed states are quick; the rest are individual work, and some
sit behind bot walls that will simply be reported as unavailable. ≈ 2–3 days for
the first state family, less thereafter.

**Phase 3 — batch screening.** `dealscope route --screen listings.csv` → a ranked
table of worth-an-NDA / verify-first / skip. ≈ 1–2 days once phase 1 is stable.

## 11. Open questions

- **Is the USDOT number available pre-NDA?** If listings withhold it, phase 1
  degrades to extraction plus questions until a number arrives — which changes
  what this is worth and where in the funnel it sits.
- **Sell-side or buy-side?** As listing QC before a listing goes live it protects
  the brokerage's credibility. As buyer verification it is a screening tool. Same
  output; different tone and default audience.
- **What is the tolerance band?** Claimed 12 trucks against 10 power units on a
  two-year-old filing may be entirely normal drift. Someone who has run a fleet
  should set that threshold, not the person writing the regex.
- **What already exists internally?** If a valuation model and comparable-deal
  data are in place, the contradiction sheet should feed them rather than
  duplicate them.
