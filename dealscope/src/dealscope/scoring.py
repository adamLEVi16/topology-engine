"""Turn extracted evidence into scores, risk flags, and open questions.

Three principles shape everything here:

1. Absence of evidence is reported as absence of evidence, never as a
   negative finding. "No pricing page" is a gap in the brief, not a verdict
   on the business.
2. Every score ships with the reasons behind it, so a reader can disagree
   with the weighting rather than having to trust it.
3. The most valuable output is not the score — it is the list of questions
   a buyer should now go and ask the seller.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from .models import (
    CompanyBrief,
    Evidence,
    RiskFlag,
    Score,
    ScoreCard,
    Signal,
)

KEY_ROLES = ("pricing", "about", "team", "careers", "contact", "blog", "legal")


def _band(value: float) -> str:
    if value < 25:
        return "thin"
    if value < 50:
        return "emerging"
    if value < 75:
        return "established"
    return "strong"


def _days_since(when: date | None, today: date) -> int | None:
    return None if when is None else (today - when).days


# --- signals ---------------------------------------------------------------


def build_signals(brief: CompanyBrief, today: date) -> list[Signal]:
    signals: list[Signal] = []

    def add(key: str, label: str, category: str, detail: str, value, weight: float,
            evidence: list[Evidence] | None = None) -> None:
        signals.append(
            Signal(key=key, label=label, category=category, detail=detail,
                   value=value, weight=weight, evidence=evidence or [])
        )

    model = brief.business_model
    if model.primary != "unknown":
        add("revenue_model", "Revenue model", "commercial",
            f"Public material reads as {model.primary} on {model.signal_count} "
            "distinct signals",
            model.primary,
            # Weight rises with breadth of evidence and tops out at 0.9. It is a
            # weight on a signal, not a claim about how likely the call is.
            min(0.9, 0.4 + 0.1 * model.signal_count))
    if model.price_points:
        add("public_pricing", "Pricing is public", "commercial",
            "Published price points make revenue easier to sanity-check",
            model.price_points[:5], 0.8)
    if model.sales_motion != "unknown":
        add("sales_motion", "Sales motion", "commercial",
            f"Calls to action point to a {model.sales_motion} motion", model.sales_motion, 0.6)

    scale = brief.scale
    if scale.leadership:
        add("named_leadership", "Named leadership", "trust",
            f"{len(scale.leadership)} leader(s) identified by name and title",
            [p["name"] for p in scale.leadership], 0.7)
    if scale.named_customers:
        add("named_customers", "Named customers", "scale",
            f"{len(scale.named_customers)} customer names visible on the site",
            scale.named_customers[:8], 0.6)
    if scale.founded_year:
        age = today.year - scale.founded_year
        add("operating_history", "Operating history", "scale",
            f"Roughly {age} year(s) of trading history claimed", age, 0.7)

    momentum = brief.momentum
    if momentum.open_roles:
        add("hiring", "Actively hiring", "momentum",
            f"{momentum.open_roles} open role(s) listed", momentum.open_roles, 0.8)
    days = _days_since(momentum.last_content_date, today)
    if days is not None:
        add("content_freshness", "Content freshness", "momentum",
            f"Most recent dated post is {days} day(s) old", days,
            0.8 if days <= 180 else 0.3)

    if brief.operations.platform_dependencies:
        add("platform_dependency", "Platform dependency", "operations",
            "Built on " + ", ".join(brief.operations.platform_dependencies),
            brief.operations.platform_dependencies, 0.5)
    if brief.trust.compliance_claims:
        add("compliance", "Compliance claims", "trust",
            "Site claims " + ", ".join(brief.trust.compliance_claims),
            brief.trust.compliance_claims, 0.5)

    return signals


# --- scores ----------------------------------------------------------------


def score_maturity(brief: CompanyBrief, today: date) -> Score:
    points = 0.0
    why: list[str] = []
    scale, model, trust = brief.scale, brief.business_model, brief.trust

    people = len(scale.named_people)
    if people >= 10:
        points += 22; why.append(f"{people} people named on the site")
    elif people >= 3:
        points += 16; why.append(f"{people} people named on the site")
    elif people >= 1:
        points += 8; why.append(f"{people} person/people named on the site")

    if scale.founded_year:
        age = today.year - scale.founded_year
        if age >= 10:
            points += 15; why.append(f"~{age} years of operating history")
        elif age >= 5:
            points += 11; why.append(f"~{age} years of operating history")
        elif age >= 2:
            points += 7; why.append(f"~{age} years of operating history")
        else:
            points += 3; why.append("founded very recently")

    if model.price_points:
        points += 10; why.append("pricing is published")
    if model.plan_names:
        points += 4; why.append(f"{len(model.plan_names)} named plans/tiers")

    customers = len(scale.named_customers)
    if customers >= 5:
        points += 12; why.append(f"{customers} named customers or logos")
    elif customers >= 1:
        points += 7; why.append(f"{customers} named customer(s)")

    legal = len(trust.legal_pages)
    if legal >= 2:
        points += 8; why.append("terms and privacy both published")
    elif legal == 1:
        points += 4; why.append("one legal page published")

    if trust.compliance_claims:
        points += 8; why.append("compliance certifications claimed")

    channels = sum(bool(x) for x in (trust.emails, trust.phones, trust.addresses))
    if channels:
        points += channels * 3
        why.append(f"{channels} contact channel(s) published")

    if len(brief.operations.tech) >= 6:
        points += 5; why.append("a real stack of production tooling in use")

    # For a local business, coverage and credentials are what maturity looks
    # like — it has no plans, no logo wall, and no reason to have them.
    # A federal filing outranks anything the site claims about itself.
    fleet = brief.fleet
    if fleet is not None and fleet.power_units:
        if fleet.power_units >= 50:
            points += 25; why.append(f"{fleet.power_units} power units on federal file")
        elif fleet.power_units >= 10:
            points += 18; why.append(f"{fleet.power_units} power units on federal file")
        elif fleet.power_units >= 3:
            points += 12; why.append(f"{fleet.power_units} power units on federal file")
        else:
            points += 5; why.append(f"{fleet.power_units} power unit(s) on federal file")

    if scale.service_areas:
        points += 8; why.append(f"publishes a service area ({scale.service_areas[0]})")
    if trust.opening_hours:
        points += 4; why.append("publishes opening hours")

    value = min(100.0, points)
    return Score(round(value, 1), _footprint_band(value), why)


def _footprint_band(value: float) -> str:
    """Describe how much the site documents, not how good the business is."""
    if value < 25:
        return "sparse"
    if value < 50:
        return "partial"
    if value < 75:
        return "substantial"
    return "comprehensive"


# Business types that have no reason to publish or to hire in public. Judging
# them on blog cadence measures the yardstick, not the company.
QUIET_BY_NATURE = ("local_services",)


def score_momentum(brief: CompanyBrief, today: date) -> Score:
    points = 0.0
    why: list[str] = []
    momentum = brief.momentum

    quiet = brief.business_model.primary in QUIET_BY_NATURE
    has_public_activity = bool(
        momentum.last_content_date or momentum.open_roles or momentum.funding_mentions
    )
    if quiet and not has_public_activity:
        # Report the one thing that is observable, and be explicit that the
        # rest is unmeasured rather than absent.
        current = (
            momentum.copyright_year is not None and today.year - momentum.copyright_year <= 1
        )
        return Score(
            value=60.0 if current else 30.0,
            band="not assessable",
            rationale=[
                "a local trade business has no reason to blog or post jobs, so "
                "publishing cadence says nothing about it",
                (
                    f"the footer copyright reads {momentum.copyright_year}, so the site is "
                    "being maintained"
                    if current
                    else "the only freshness signal available is the footer copyright"
                    + (f", which reads {momentum.copyright_year}" if momentum.copyright_year else ", which is absent")
                ),
                "ask for job volumes, crew utilisation, and repeat-customer rate instead",
            ],
            assessable=False,
        )

    if momentum.open_roles:
        if momentum.open_roles >= 10:
            points += 30; why.append(f"{momentum.open_roles} open roles")
        elif momentum.open_roles >= 3:
            points += 24; why.append(f"{momentum.open_roles} open roles")
        else:
            points += 16; why.append(f"{momentum.open_roles} open role(s)")
    elif momentum.open_roles == 0:
        points += 4; why.append("careers page live but no open roles")

    days = _days_since(momentum.last_content_date, today)
    if days is not None:
        if days <= 60:
            points += 30; why.append("published within the last two months")
        elif days <= 180:
            points += 22; why.append("published within the last six months")
        elif days <= 365:
            points += 12; why.append("last published within the year")
        elif days <= 730:
            points += 5; why.append("last published over a year ago")
        else:
            why.append("no new content in more than two years")

    if momentum.posts_per_month:
        if momentum.posts_per_month >= 4:
            points += 15; why.append(f"~{momentum.posts_per_month} posts/month")
        elif momentum.posts_per_month >= 1:
            points += 10; why.append(f"~{momentum.posts_per_month} posts/month")
        else:
            points += 5

    if momentum.copyright_year:
        delta = today.year - momentum.copyright_year
        if delta <= 1:
            points += 12; why.append("footer copyright is current")
        elif delta == 2:
            points += 5
        else:
            why.append(f"footer copyright last updated {momentum.copyright_year}")

    if momentum.funding_mentions:
        points += 10; why.append("funding or investor activity mentioned")
    if len(momentum.hiring_departments) >= 3:
        points += 5; why.append("hiring across several departments")

    value = min(100.0, points)
    return Score(round(value, 1), _band(value), why)


def score_transparency(brief: CompanyBrief) -> Score:
    points = 0.0
    why: list[str] = []
    trust, scale = brief.trust, brief.scale

    if scale.leadership:
        points += 20; why.append("leadership named with titles")
    elif scale.named_people:
        points += 10; why.append("team members named")

    if trust.addresses:
        points += 15; why.append("physical address published")
    if trust.phones:
        points += 10; why.append("phone number published")
    if trust.emails:
        points += 10; why.append("email address published")

    legal = len(trust.legal_pages)
    if legal >= 2:
        points += 15; why.append("terms and privacy policy both reachable")
    elif legal == 1:
        points += 8; why.append("one legal page reachable")

    if trust.compliance_claims:
        points += 10; why.append("compliance posture described publicly")
    if brief.business_model.price_points:
        points += 10; why.append("pricing published rather than gated")
    if len(trust.socials) >= 2:
        points += 10; why.append(f"{len(trust.socials)} social profiles linked")

    value = min(100.0, points)
    return Score(round(value, 1), _band(value), why)


def score_coverage(brief: CompanyBrief) -> Score:
    """How much of the site we actually managed to read.

    This is a confidence gauge on the brief itself, not a judgement about the
    company. A low score here means treat everything above with caution.
    """
    fetched = [p for p in brief.pages if not p.get("error")]
    roles_found = {p["role"] for p in fetched}
    covered = [role for role in KEY_ROLES if role in roles_found]

    points = 100.0 * len(covered) / len(KEY_ROLES) * 0.75
    words = sum(p.get("words", 0) for p in fetched)
    if words >= 6000:
        points += 25
    elif words >= 2500:
        points += 18
    elif words >= 800:
        points += 10
    elif words >= 200:
        points += 4

    why = [f"{len(fetched)} page(s) read, ~{words:,} words"]
    if covered:
        why.append("found: " + ", ".join(covered))
    missing = [role for role in KEY_ROLES if role not in roles_found]
    if missing:
        why.append("not found: " + ", ".join(missing))

    value = min(100.0, points)
    return Score(round(value, 1), _band(value), why)


def build_scores(brief: CompanyBrief, today: date) -> ScoreCard:
    return ScoreCard(
        maturity=score_maturity(brief, today),
        momentum=score_momentum(brief, today),
        transparency=score_transparency(brief),
        evidence_coverage=score_coverage(brief),
    )


# --- risk flags ------------------------------------------------------------


def build_risk_flags(
    brief: CompanyBrief,
    today: date,
    client_rendered: bool = False,
    robots_blocked: int = 0,
) -> list[RiskFlag]:
    flags: list[RiskFlag] = []
    trust, scale, momentum, model = brief.trust, brief.scale, brief.momentum, brief.business_model
    home_words = next(
        (p.get("words", 0) for p in brief.pages if p.get("role") == "home"), 0
    )
    # "Not found" only means "not readable by this tool" when the site renders
    # its navigation in the browser or excludes readers via robots.txt. Every
    # absence-based flag has to say so rather than imply a real gap.
    limits: list[str] = []
    if client_rendered:
        limits.append("renders much of its navigation client-side")
    if robots_blocked:
        limits.append(f"disallows {robots_blocked} of the pages tried via robots.txt")
    caveat = (
        " Note that this site " + " and ".join(limits) + ", so this may be a limit "
        "of what could be read rather than a real gap."
        if limits
        else ""
    )

    if home_words < 120:
        flags.append(RiskFlag(
            "thin_site", "Homepage has almost no content", "high",
            f"The homepage yielded only ~{home_words} words. That can mean a "
            "placeholder, a parked domain, or a site that renders entirely in "
            "JavaScript — this tool reads server-rendered HTML only.",
        ))

    days = _days_since(momentum.last_content_date, today)
    stale_copyright = (
        momentum.copyright_year is not None and today.year - momentum.copyright_year >= 3
    )
    if (days is not None and days > 540) or stale_copyright:
        detail = []
        if days is not None and days > 540:
            detail.append(f"newest dated post is {days} days old")
        if stale_copyright:
            detail.append(f"footer copyright still reads {momentum.copyright_year}")
        flags.append(RiskFlag(
            "stale_site", "Site looks neglected", "high",
            "Signs the site has not been maintained: " + "; ".join(detail) + ". "
            "Worth establishing whether the business is still trading normally.",
            evidence=[e for e in momentum.evidence
                      if e.field in ("momentum.last_post", "momentum.copyright_year")],
        ))

    if not trust.emails and not trust.phones and not trust.addresses:
        flags.append(RiskFlag(
            "no_contact", "No contact details published", "high",
            "No email, phone, or postal address was found. This complicates "
            "verifying who actually operates the business." + caveat,
        ))

    if not scale.named_people:
        flags.append(RiskFlag(
            "no_people", "Nobody is named publicly", "medium",
            "No owners, founders, or staff are identified on the site. Ownership "
            "and key-person dependency will have to be established directly." + caveat,
        ))
    elif len(scale.named_people) == 1:
        flags.append(RiskFlag(
            "key_person", "Appears to be a one-person operation", "medium",
            f"Only one person ({scale.named_people[0]['name']}) is named. If the "
            "business depends on them, transferability is the central question.",
        ))

    # A trade business quotes every job, so absent prices are the norm rather
    # than a finding. Raising it as a flag would be noise dressed as insight.
    if not model.price_points and model.primary not in ("local_services", "services"):
        flags.append(RiskFlag(
            "no_public_pricing", "Pricing is not published", "medium",
            "Without public prices, revenue cannot be sanity-checked from the "
            "outside at all. Expect to rely entirely on seller-provided figures." + caveat,
        ))

    if not trust.legal_pages:
        flags.append(RiskFlag(
            "no_legal_pages", "No terms or privacy policy found", "medium",
            "Missing legal pages can indicate an immature operation, and in some "
            "jurisdictions is itself a compliance gap the buyer inherits." + caveat,
        ))

    if brief.operations.platform_dependencies:
        platforms = ", ".join(brief.operations.platform_dependencies)
        flags.append(RiskFlag(
            "platform_dependency", f"Built on {platforms}", "low",
            f"The business runs on {platforms}. Confirm the platform account, "
            "domain, and any custom theme or plugin code transfer with the sale.",
            evidence=[e for e in brief.operations.evidence
                      if e.value in brief.operations.platform_dependencies],
        ))

    if trust.compliance_claims:
        claimed = ", ".join(trust.compliance_claims)
        if model.primary == "local_services":
            flags.append(RiskFlag(
                "unverified_credentials", "Licences and insurance are unverified", "low",
                f"The site claims {claimed}. That is marketing copy — ask for the "
                "current licence numbers and certificates of insurance, and check "
                "they are held by the entity being sold and transfer on completion.",
            ))
        else:
            flags.append(RiskFlag(
                "unverified_compliance", "Compliance claims are unverified", "low",
                f"The site claims {claimed}. These were read off marketing copy — "
                "ask for the current audit reports.",
            ))

    fleet = brief.fleet
    if fleet is not None:
        if not fleet.is_active:
            flags.append(RiskFlag(
                "carrier_inactive", "Federal carrier authority is not active", "high",
                f"FMCSA shows USDOT {fleet.usdot} as “{fleet.operating_status or 'not active'}”"
                + (f", out of service since {fleet.out_of_service_date}" if fleet.out_of_service_date else "")
                + ". A carrier that cannot legally operate is a different purchase entirely.",
                evidence=[e for e in fleet.evidence if e.field.startswith("fleet.operating")],
            ))
        if fleet.mcs150_date is not None and (today - fleet.mcs150_date).days > 730:
            flags.append(RiskFlag(
                "stale_mcs150", "Federal registration details look stale", "medium",
                f"The MCS-150 was last filed on {fleet.mcs150_date.isoformat()}, over two "
                "years ago. Carriers must update it biennially, so the fleet and driver "
                "counts above may be out of date — and late filing can suspend the "
                "USDOT number.",
                evidence=[e for e in fleet.evidence if e.field == "fleet.mcs150_date"],
            ))
    elif brief.fleet_note_kind == "inactive":
        # A number that exists and has lost its authority is a finding, and a
        # serious one — not a failure to match.
        flags.append(RiskFlag(
            "carrier_inactive_record", "Federal operating authority is not live", "high",
            brief.fleet_note,
        ))
    elif brief.fleet_note_kind == "unmatched":
        flags.append(RiskFlag(
            "carrier_unmatched", "Could not confidently match a federal carrier record", "low",
            brief.fleet_note + ". Ask the seller for the USDOT number directly rather "
            "than relying on a name match.",
        ))
    # "absent" and "unreachable" raise nothing on purpose. A fleet under 10,001
    # lbs GVWR needs no USDOT number, so no record is not a finding about the
    # business; and a register that timed out is a fact about the register. The
    # note still prints — it just is not dressed up as a risk. Matching on the
    # note's wording instead of this field is what turned all three into one.

    errors = [p for p in brief.pages if p.get("error")]
    if len(errors) >= 3:
        flags.append(RiskFlag(
            "fetch_failures", "Several pages could not be read", "low",
            f"{len(errors)} page(s) failed to load or were blocked. The brief is "
            "working from a partial view of the site.",
        ))

    flags.sort(key=lambda f: f.rank)
    return flags


# --- unknowns and questions ------------------------------------------------

# Nothing on a public website can answer these, for any company.
STRUCTURAL_UNKNOWNS = [
    "Revenue, margins, and profitability",
    "Customer concentration and churn",
    "Cost base, including staff and platform costs",
    "Owner involvement and how transferable the operation is",
    "Existing contracts, liabilities, and any litigation",
    "Ownership of IP, domains, and third-party accounts",
]


def build_unknowns(brief: CompanyBrief) -> list[str]:
    unknowns = list(STRUCTURAL_UNKNOWNS)
    # Which pages were actually read. Saying "no careers page was found" while
    # the brief lists one under "Pages read" is the kind of contradiction that
    # makes a reader distrust everything else.
    roles_read = {p.get("role") for p in brief.pages if not p.get("error")}

    if not brief.business_model.price_points:
        unknowns.append("Pricing — nothing public was found")
    if not brief.scale.named_people:
        unknowns.append("Who owns and runs the business")
    if brief.momentum.open_roles is None:
        unknowns.append(
            "Hiring activity — the careers page listed nothing countable"
            if "careers" in roles_read
            else "Hiring activity — no careers page was found"
        )
    if brief.momentum.last_content_date is None:
        unknowns.append(
            "Publishing cadence — the blog carried no readable dates"
            if "blog" in roles_read
            else "Publishing cadence — no dated content was found"
        )
    if not brief.scale.named_customers and not brief.scale.customer_count_claim:
        unknowns.append("Customer base — no customers or counts are named publicly")
    if brief.business_model.primary == "unknown":
        unknowns.append("How the business actually charges — the site does not make it clear")
    return unknowns


MODEL_QUESTIONS: dict[str, list[str]] = {
    "saas": [
        "What are current MRR/ARR, and the growth rate over the last 24 months?",
        "What is gross and net revenue retention, and monthly logo churn?",
        "What share of revenue comes from the top 10 accounts?",
        "What is customer acquisition cost and payback period, by channel?",
        "How much of the base is on annual vs monthly contracts, and are they assignable?",
        "What does infrastructure cost per customer, and how does it scale?",
    ],
    "ecommerce": [
        "What are revenue, gross margin, and contribution margin by SKU?",
        "What are average order value and repeat purchase rate?",
        "Who are the suppliers, and are the agreements exclusive and transferable?",
        "What inventory is on hand, and how is it valued?",
        "What share of traffic and revenue is paid, and what is blended ROAS?",
        "What is the returns and chargeback rate?",
    ],
    "local_services": [
        "What were revenue and gross margin per job over the last three years, by service line?",
        "What share of work is recurring contracts versus one-off callouts?",
        "How seasonal is the work, and what does the slowest quarter look like?",
        "How many crews and licensed technicians are there, and what is staff turnover?",
        "Which licences and insurance policies are held, in whose name, and do they transfer?",
        "Are vehicles, plant, and equipment owned, financed, or leased — and what is their condition?",
        "How much selling and estimating does the owner personally do?",
        "Where does new work come from — referrals, Google, trucks, or paid ads?",
    ],
    "services": [
        "What is revenue by client, and what share is the largest client?",
        "What is the split between recurring retainers and one-off projects?",
        "What are utilisation rates and average billing rates?",
        "How much delivery work does the owner personally perform?",
        "What does the signed pipeline look like for the next two quarters?",
        "Which staff are critical, and what are their notice periods?",
    ],
    "marketplace": [
        "What are GMV, take rate, and net revenue over the last 24 months?",
        "How concentrated are both supply and demand sides?",
        "What is liquidity — match rate and time to fill?",
        "What are repeat rates for buyers and for sellers?",
        "How much of supply is exclusive to this platform?",
    ],
    "media": [
        "What are traffic volumes and sources, and how exposed are they to search algorithm changes?",
        "What is the split between advertising, sponsorship, subscription, and affiliate revenue?",
        "How concentrated are sponsors or advertisers?",
        "What is the email list size, and its open and click rates?",
        "Who creates the content, and do they stay after a sale?",
    ],
    "hardware": [
        "What are unit economics — COGS, landed cost, and gross margin?",
        "How concentrated is the supplier base, and are contracts transferable?",
        "What inventory and tooling is owned, and where does it sit?",
        "What are warranty, defect, and return rates?",
        "What certifications does the product hold, and do they transfer?",
    ],
}

UNIVERSAL_QUESTIONS = [
    "Can you provide three years of P&L, balance sheet, and tax returns?",
    "Why are you selling, and what happens to you post-close?",
    "What would break if the current owner stopped working tomorrow?",
    "Are all domains, platform accounts, and IP owned by the selling entity?",
]


def build_diligence_questions(brief: CompanyBrief) -> list[str]:
    questions: list[str] = []
    questions.extend(MODEL_QUESTIONS.get(brief.business_model.primary, []))

    if brief.operations.platform_dependencies:
        platforms = ", ".join(brief.operations.platform_dependencies)
        questions.append(
            f"The site runs on {platforms} — who holds the account, and does it transfer at close?"
        )
    if brief.momentum.last_content_date is None or (
        brief.momentum.copyright_year
        and datetime.now(timezone.utc).year - brief.momentum.copyright_year >= 3
    ):
        questions.append(
            "The site shows little recent activity — is the business still trading at normal volume?"
        )
    if len(brief.scale.named_people) <= 1:
        questions.append(
            "Who else works in the business, as employees or contractors, and on what terms?"
        )
    if brief.trust.compliance_claims:
        questions.append(
            "Can you share the current audit reports behind the "
            + ", ".join(brief.trust.compliance_claims)
            + " claims?"
        )

    questions.extend(UNIVERSAL_QUESTIONS)

    seen: set[str] = set()
    ordered: list[str] = []
    for question in questions:
        if question.lower() not in seen:
            seen.add(question.lower())
            ordered.append(question)
    return ordered[:14]
