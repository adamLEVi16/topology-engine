"""How does this business make money?

The single most useful thing a brief can tell an acquirer, and the thing a
homepage tagline almost never says outright. Inferred from pricing pages,
calls to action, commerce platform fingerprints, and vocabulary.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from ..fetch import make_soup
from ..models import (
    ROLE_ABOUT,
    ROLE_HOME,
    ROLE_PRICING,
    ROLE_PRODUCT,
    BusinessModel,
    Evidence,
    Page,
)
from . import structured as st

# Weighted vocabulary per revenue model. Weights are deliberately modest so
# that no single phrase can decide the answer on its own.
MODEL_SIGNALS: dict[str, tuple[tuple[str, float], ...]] = {
    "saas": (
        (r"\bper\s+(user|seat|month|editor|agent)\b", 3.0),
        (r"\b(subscription|subscribe now|billed (monthly|annually|yearly))\b", 2.5),
        (r"\bfree trial\b", 2.0),
        (r"\b(start(ing)? free|sign up free|get started free)\b", 1.5),
        (r"\b(dashboard|integrations?|api key|workspace|single sign-on|sso)\b", 1.0),
        (r"\b(cancel any\s?time|no credit card required)\b", 1.5),
        (r"/mo\b|/month\b|/year\b|\bmo\.\b", 2.0),
    ),
    "ecommerce": (
        (r"\badd to (cart|bag|basket)\b", 4.0),
        (r"\b(free shipping|shipping (rates|policy)|delivery times?)\b", 2.5),
        (r"\b(returns? policy|refund policy|exchanges?)\b", 1.5),
        (r"\b(in stock|out of stock|sold out|sizes?\b.*\bcolou?rs?)\b", 2.0),
        (r"\b(shop (now|all)|our (store|shop)|browse products)\b", 2.0),
        (r"\b(checkout|your (cart|bag))\b", 2.0),
    ),
    "services": (
        (r"\b(our clients|work with us|book a (call|consultation)|free consultation)\b", 3.0),
        (r"\b(consultancy|consulting|advisory|bespoke|tailored to your)\b", 2.5),
        (r"\b(case stud(y|ies)|our (process|approach)|engagements?)\b", 1.5),
        (r"\b(hourly rate|per project|statement of work|retainer)\b", 3.0),
        (r"\b(we (design|build|help|deliver)|our team (will|can))\b", 1.0),
        (r"\b(request a (quote|proposal)|get a quote)\b", 2.0),
    ),
    # Main Street businesses — landscapers, HVAC, plumbers, salons, clinics.
    # They speak a different language from B2B consultancies: they sell a visit,
    # not an engagement, and the whole site is built around phoning them.
    "local_services": (
        (r"\b(free (estimate|quote|inspection)|no obligation (quote|estimate))\b", 4.0),
        (r"\b(licen[cs]ed (and|&) insured|fully insured|bonded (and|&) insured)\b", 4.0),
        (r"\b(call (now|us|today)|give us a call|call for a)\b", 2.5),
        (r"\b(schedule (an |your )?(appointment|service|visit|consultation)|book (online|now|a visit))\b", 3.0),
        # (?-i:[A-Z]) because _count matches every pattern here with re.I, which
        # silently defeated this [A-Z] — the same defect that once let a SaaS
        # homepage publish a service area. Without it, "serving replica" in an
        # article scored a tech newsletter as a trade business.
        (r"\b(serving\s+(?-i:[A-Z])[\w.\- ]{2,40}(county|area|and surrounding|since)?|service area|areas we serve)\b", 3.0),
        (r"\b(residential (and|&) commercial|commercial (and|&) residential)\b", 3.0),
        (r"\b(emergency (service|repair|call)|24/7|same[- ]day service)\b", 2.5),
        (r"\b(family[- ]owned|locally owned|third[- ]generation|second[- ]generation)\b", 2.5),
        (r"\b(installation|repair|maintenance|cleanup|inspection)s?\b", 1.0),
        (r"\b(satisfaction guaranteed|free consultation|senior discount|financing available)\b", 1.5),
    ),
    "marketplace": (
        (r"\b(buyers? and sellers?|sellers?|vendors?|merchants?)\b", 2.0),
        (r"\b(list(ing)?s? (on|your)|become a (seller|host|partner|provider))\b", 3.0),
        (r"\b(commission|take rate|transaction fee)\b", 2.5),
        (r"\b(browse (listings|providers)|find a (pro|provider|supplier))\b", 2.0),
    ),
    "media": (
        (r"\b(advertise with us|sponsorships?|media kit|ad rates)\b", 3.5),
        (r"\b(newsletter|subscribers|our readers|editorial)\b", 1.5),
        (r"\b(paywall|members? only|become a (member|supporter)|patron)\b", 2.5),
    ),
    "hardware": (
        (r"\b(specifications?|dimensions|warranty|ships? within)\b", 2.0),
        (r"\b(device|hardware|unit|assembly|installation guide)\b", 1.5),
        (r"\b(distributors?|resellers?|wholesale)\b", 2.0),
    ),
}

MODEL_LABELS = {
    "saas": "Software subscription (SaaS)",
    "ecommerce": "E-commerce / direct product sales",
    "services": "Services / consulting",
    "local_services": "Local trade services (jobs and callouts)",
    "marketplace": "Marketplace / platform",
    "media": "Media, content, or advertising",
    "hardware": "Hardware / physical products",
    "unknown": "Not determinable from the public site",
}

# The same labels phrased to drop into a sentence.
MODEL_PHRASES = {
    "saas": "software subscriptions",
    "ecommerce": "direct product sales",
    "services": "services and consulting work",
    "local_services": "quoted jobs and callouts for local customers",
    "marketplace": "marketplace or platform transactions",
    "media": "media, content, or advertising",
    "hardware": "hardware and physical product sales",
    "unknown": "an unclear mix",
}

SELF_SERVE = re.compile(
    r"\b(sign ?up|get started|buy now|add to (cart|bag|basket)|create (an )?account|"
    # "Start your 14-day free trial" and its many variants.
    r"start (your |a |the )?(\d{1,3}[- ]day )?(free )?(trial|plan)|"
    r"try (it |us )?(for )?free|free trial|start free|no credit card required)\b",
    re.I,
)
SALES_LED = re.compile(
    r"\b(contact sales|talk to (sales|us)|book a (demo|call)|request a (demo|quote|proposal)|"
    r"get in touch|schedule a (demo|call)|custom pricing|enterprise pricing|"
    # Local businesses sell the same way: they want you to call or ask.
    r"get a (quote|estimate)|free estimate|request service|"
    r"schedule (an |your )?(appointment|service|visit)|call (now|today|us))\b",
    re.I,
)

PLAN_WORDS = re.compile(
    r"^\s*(free|freemium|starter|basic|essentials?|lite|standard|plus|pro|professional|premium|"
    r"growth|team|teams|business|company|scale|advanced|enterprise|ultimate|custom|personal|"
    r"individual|hobby|solo|agency|unlimited)\s*(plan|tier|package)?\s*$",
    re.I,
)

# Tiers are often named for the customer rather than the size: "Practice",
# "Clinic", "Studio". A short title-case line sitting right against a price is
# accepted as a plan name even when it is not in the vocabulary above.
GENERIC_PLAN_LINE = re.compile(r"^[A-Z][A-Za-z&+/'’ -]{1,22}$")

# A pricing table puts the price on its own line. Anything longer is a sentence.
TABLE_PRICE_MAX_CHARS = 40
# …and a table cell is mostly the price, not a clause containing one. "We
# raised $2.5M in seed funding." is under the character limit and is not a price.
TABLE_PRICE_MAX_WORDS = 4

# Enough weight, and enough *different* signals, to call a revenue model.
MIN_MODEL_SCORE = 5.0
MIN_MODEL_SIGNALS = 3
# How close the runner-up has to be before it is worth telling the reader about.
CLOSE_SECOND = 0.75

NAV_WORDS = {
    "about", "blog", "careers", "contact", "company", "cookies", "docs",
    "documentation", "download", "faq", "features", "help", "home", "legal",
    "login", "log in", "logout", "menu", "news", "overview", "partners",
    "press", "pricing", "privacy", "product", "products", "resources", "search",
    "security", "services", "settings", "sign in", "sign up", "solutions",
    "support", "terms", "why us",
}


def _generic_plan_name(line: str) -> bool:
    if not GENERIC_PLAN_LINE.match(line) or any(ch.isdigit() for ch in line):
        return False
    words = line.split()
    if len(words) > 2 or line.lower() in NAV_WORDS:
        return False
    return True

# Two shapes, because half the world writes the symbol after the number and
# uses a comma as the decimal separator. "€29,99" read as €29 before — a wrong
# price stated as a published one — and "29,99 €" was invisible entirely.
_AMOUNT = r"\d{1,3}(?:[.,\s]\d{3})*(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
_SYMBOL = r"[$£€¥]|USD|EUR|GBP|CAD|AUD|CHF|SEK|NOK|DKK|PLN"

PRICE = re.compile(
    rf"(?P<sym>{_SYMBOL})\s?(?P<amt>{_AMOUNT})"
    rf"|(?P<amt2>{_AMOUNT})\s?(?P<sym2>{_SYMBOL})(?![A-Za-z])",
    re.I,
)


def parse_amount(text: str) -> float | None:
    """Read a price string under either separator convention.

    A trailing group of exactly two digits after ``,`` or ``.`` is a decimal;
    groups of three are thousands separators.
    """
    cleaned = (text or "").replace(" ", "")
    if not cleaned:
        return None
    decimal = re.search(r"[.,](\d{1,2})$", cleaned)
    if decimal:
        whole = re.sub(r"[^\d]", "", cleaned[: decimal.start()])
        return float(f"{whole or 0}.{decimal.group(1)}")
    digits = re.sub(r"[^\d]", "", cleaned)
    return float(digits) if digits else None
PERIOD = re.compile(
    r"\bper\s+(month|year|user|seat|month,? billed \w+|annum)\b|/\s?(mo|month|yr|year|user|seat)\b",
    re.I,
)
FREE_TIER = re.compile(
    r"\b(free (plan|tier|forever|for ever)|\$0\s?(/|per)|free for (individuals|personal|up to)|"
    r"always free|no cost)\b",
    re.I,
)
TRIAL = re.compile(r"\b(\d{1,3})[- ]day (free )?trial\b", re.I)

_SYMBOL_TO_CODE = {"$": "USD", "£": "GBP", "€": "EUR", "¥": "JPY"}


def _count(pattern: str, text: str, cap: int = 3) -> int:
    return min(len(re.findall(pattern, text, re.I)), cap)


# A number inside a testimonial belongs to the customer, not the price list.
# "It saved us $30,000 in the first year" is the single most quoted sentence
# shape on a B2B homepage, and it was being published as a price point.
QUOTE_TAGS = ("blockquote", "q", "cite", "figcaption")
QUOTE_CLASS = re.compile(r"testimonial|quote|review|case-?stud", re.I)


def _quoted_text(page: Page) -> str:
    """Everything on the page that is somebody being quoted, flattened."""
    soup = make_soup(page.html)
    parts = [tag.get_text(" ", strip=True) for tag in soup.find_all(QUOTE_TAGS)]
    parts += [
        tag.get_text(" ", strip=True) for tag in soup.find_all(attrs={"class": QUOTE_CLASS})
    ]
    return " ".join(" ".join(part.split()) for part in parts if part)


def _is_table_price(line: str) -> bool:
    """Does this line read as a pricing-table cell rather than a sentence?

    Length alone is not enough: "We raised $2.5M in seed funding." fits inside
    the character limit. A cell is also only a handful of words.
    """
    return len(line) <= TABLE_PRICE_MAX_CHARS and len(line.split()) <= TABLE_PRICE_MAX_WORDS


def _extract_prices(pages: list[Page]) -> tuple[list[str], str, list[Evidence]]:
    """Distinct price points, most prominent currency, and their sources."""
    found: list[tuple[float, str, str]] = []  # (amount, formatted, source url)
    symbols: Counter[str] = Counter()

    for page in pages:
        # A dedicated pricing page is all price list, so numbers there are
        # taken at face value. Anywhere else a number has to earn it — the same
        # discipline plan names already get.
        on_pricing_page = page.role == ROLE_PRICING
        quoted = "" if on_pricing_page else _quoted_text(page)

        for line in page.text.splitlines():
            stripped = " ".join(line.split())
            if not stripped:
                continue
            if quoted and stripped in quoted:
                continue
            for match in PRICE.finditer(line):
                amount = parse_amount(match.group("amt") or match.group("amt2") or "")
                if amount is None:
                    continue
                # Skip years, phone fragments, and implausible headline numbers.
                if amount <= 0 or amount > 100_000:
                    continue
                period = PERIOD.search(line[match.end() : match.end() + 40])
                # Off a pricing page, either a billing period follows ("£29 per
                # month" on a homepage is a real price) or the line is a table
                # cell. Otherwise it is prose about money, not a price.
                if not on_pricing_page and not period and not _is_table_price(stripped):
                    continue
                symbol = match.group("sym") or match.group("sym2") or ""
                code = _SYMBOL_TO_CODE.get(symbol, symbol.upper())
                symbols[code] += 1
                display = match.group(0).strip()
                if period:
                    display = f"{display} {period.group(0).strip()}"
                found.append((amount, " ".join(display.split()), page.final_url))

    if not found:
        return [], "", []

    currency = symbols.most_common(1)[0][0]
    seen: set[str] = set()
    unique: list[tuple[float, str, str]] = []
    for amount, display, url in sorted(found, key=lambda t: t[0]):
        key = display.lower()
        if key not in seen:
            seen.add(key)
            unique.append((amount, display, url))

    top = unique[:8]
    evidence = [
        Evidence("business_model.price_point", display, url, "regex", 0.7)
        for _amount, display, url in top[:5]
    ]
    return [display for _a, display, _u in top], currency, evidence


def _extract_plans(pages: list[Page]) -> tuple[list[str], list[Evidence]]:
    """Plan and tier names, taken only from lines sitting beside a price.

    Words like "Business" and "Company" are as likely to be footer navigation
    as pricing tiers. Proximity to an actual price is what separates the two.
    """
    names: list[str] = []
    evidence: list[Evidence] = []

    for page in pages:
        lines = page.text.splitlines()
        # Only prices that stand alone count as table prices. A price mentioned
        # inside a sentence is FAQ prose, and the words beside it are features,
        # not tiers — that is how "Timesheet" became a Basecamp "plan".
        price_lines = {
            i
            for i, line in enumerate(lines)
            if PRICE.search(line) and len(line) <= TABLE_PRICE_MAX_CHARS
        }
        if not price_lines:
            continue
        for index, line in enumerate(lines):
            if len(line) > 30 or PRICE.search(line):
                continue
            if PLAN_WORDS.match(line):
                # "Free", "Enterprise" and friends are unambiguous; being near a
                # price on either side is enough.
                if min((abs(index - p) for p in price_lines), default=99) > 4:
                    continue
            elif _generic_plan_name(line):
                # An unrecognised word is only a tier if it heads a pricing card
                # on a real pricing page — that is, the price follows it, as in
                # "Practice / £79". Without that, a shop's "Spend $50, get free
                # Shipping" banner reads as two pricing tiers.
                if page.role != ROLE_PRICING:
                    continue
                if not any(index < p <= index + 3 for p in price_lines):
                    continue
            else:
                continue
            label = " ".join(line.split()).title()
            if label.lower() not in {n.lower() for n in names}:
                names.append(label)
                evidence.append(
                    Evidence("business_model.plan", label, page.final_url, "regex", 0.6)
                )

    return names[:8], evidence[:8]


# Facts a business that sells callouts publishes, and a B2B consultancy
# generally does not. Vocabulary alone had to separate "we serve our clients"
# from "we serve Dayton and Springfield", and it kept getting that wrong. These
# are structural — a phone in the masthead, opening hours, a named service
# area, a street address — and the classification leans on them directly.
LOCAL_CONTACT_FEATURES: tuple[tuple[str, str, float], ...] = (
    ("service_areas", "a published service area", 3.0),
    ("phone_in_header", "a phone number in the site header", 2.5),
    ("opening_hours", "published opening hours", 2.0),
    ("addresses", "a published street address", 1.5),
)


def extract(
    pages: list[Page],
    platform_hints: list[str] | None = None,
    contact_facts: dict[str, Any] | None = None,
) -> tuple[BusinessModel, list[Evidence]]:
    """Infer the revenue model and pull whatever pricing detail is public."""
    model = BusinessModel()
    evidence: list[Evidence] = []
    pricing_pages = st.pages_by_role(pages, ROLE_PRICING)
    corpus = st.joined_text(
        st.pages_by_role(pages, ROLE_HOME, ROLE_PRICING, ROLE_PRODUCT, ROLE_ABOUT), 80_000
    )
    home_url = next(
        (p.final_url for p in pages if p.role == ROLE_HOME and p.ok),
        pages[0].final_url if pages else "",
    )

    # --- score each revenue model ---
    scores: dict[str, float] = {}
    top_hits: dict[str, list[str]] = {}
    for name, patterns in MODEL_SIGNALS.items():
        total = 0.0
        hits: list[str] = []
        for pattern, weight in patterns:
            count = _count(pattern, corpus)
            if count:
                total += weight * count
                sample = re.search(pattern, corpus, re.I)
                if sample:
                    hits.append(sample.group(0).strip())
        scores[name] = total
        top_hits[name] = hits

    # Platform fingerprints are strong, direct evidence of how sales happen.
    for hint in platform_hints or []:
        lowered = hint.lower()
        if lowered in ("shopify", "woocommerce", "bigcommerce", "magento", "squarespace commerce"):
            scores["ecommerce"] = scores.get("ecommerce", 0) + 8.0
            top_hits.setdefault("ecommerce", []).append(hint)
        elif lowered in ("stripe", "paddle", "chargebee", "recurly"):
            scores["saas"] = scores.get("saas", 0) + 2.5
            top_hits.setdefault("saas", []).append(hint)

    for key, label, weight in LOCAL_CONTACT_FEATURES:
        if (contact_facts or {}).get(key):
            scores["local_services"] = scores.get("local_services", 0.0) + weight
            top_hits.setdefault("local_services", []).append(label)

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    best, best_score = ranked[0]
    # Breadth, not just weight. One heavily weighted phrase repeated three
    # times used to clear the bar on its own; requiring several *different*
    # signals is what separates a real reading from an echo.
    distinct = len(dict.fromkeys(top_hits.get(best, [])))

    if best_score >= MIN_MODEL_SCORE and distinct >= MIN_MODEL_SIGNALS:
        model.primary = best
        model.signal_count = distinct
        # "A close second reading" has to mean it. At the old 45% cut this said
        # a tech newsletter might be a local trade business — true of the
        # arithmetic, false of the company, and now printed in the narrative.
        model.secondary = [
            name for name, score in ranked[1:3] if score >= best_score * CLOSE_SECOND
        ]
        sample = ", ".join(dict.fromkeys(top_hits.get(best, [])))[:180]
        evidence.append(
            Evidence(
                "business_model.primary",
                MODEL_LABELS[best],
                home_url,
                "heuristic",
                # Evidence confidence is about this one observation, not a
                # probability that the model is right.
                0.7,
                snippet=(
                    f"{distinct} distinct signals matched: {sample}" if sample else ""
                ),
            )
        )
    else:
        model.primary = "unknown"
        model.signal_count = 0

    # --- sales motion ---
    self_serve = len(SELF_SERVE.findall(corpus))
    sales_led = len(SALES_LED.findall(corpus))
    if self_serve or sales_led:
        if self_serve >= 2 and sales_led >= 2:
            model.sales_motion = "hybrid"
        elif self_serve > sales_led:
            model.sales_motion = "self-serve"
        else:
            model.sales_motion = "sales-led"
        # A consultancy cannot be bought without talking to anyone. "Get
        # started" on an agency site opens a conversation, not a checkout, so
        # without published prices the motion is sales-led whatever the CTAs say.
        if model.primary in ("services", "local_services") and not model.price_points:
            model.sales_motion = "sales-led"

        example = (SELF_SERVE.search(corpus) if self_serve >= sales_led else SALES_LED.search(corpus))
        evidence.append(
            Evidence(
                "business_model.sales_motion",
                model.sales_motion,
                home_url,
                "heuristic",
                0.6,
                snippet=f"calls to action such as “{example.group(0)}”" if example else "",
            )
        )

    # --- pricing detail ---
    # Always search the homepage and product pages as well as any dedicated
    # pricing page: plenty of sites put the price table on the homepage, and a
    # "pricing" page that turns out to be documentation should not hide it.
    price_sources = pricing_pages + st.pages_by_role(pages, ROLE_HOME, ROLE_PRODUCT)
    model.price_points, model.currency, price_evidence = _extract_prices(price_sources)
    evidence.extend(price_evidence)

    model.plan_names, plan_evidence = _extract_plans(price_sources)
    evidence.extend(plan_evidence)

    periods = {match.group(0).strip().lower() for match in PERIOD.finditer(corpus)}
    model.billing_periods = sorted(periods)[:6]

    free_match = FREE_TIER.search(corpus)
    if free_match:
        model.has_free_tier = True
        evidence.append(
            Evidence("business_model.free_tier", "yes", home_url, "regex", 0.7,
                     snippet=free_match.group(0))
        )
    elif pricing_pages:
        model.has_free_tier = False

    trial = TRIAL.search(corpus)
    if trial:
        evidence.append(
            Evidence("business_model.trial", trial.group(0), home_url, "regex", 0.75)
        )

    # JSON-LD offers are authoritative when present; record them explicitly.
    for page in pricing_pages or pages[:1]:
        for offer in st.of_type(st.json_ld_objects(page.html), "Offer", "AggregateOffer"):
            price = st.text_of(offer.get("price") or offer.get("lowPrice"))
            currency = st.text_of(offer.get("priceCurrency"))
            if price:
                label = f"{currency} {price}".strip()
                evidence.append(
                    Evidence("business_model.price_point", label, page.final_url, "json-ld", 0.9)
                )
                if label not in model.price_points:
                    model.price_points.insert(0, label)
                if currency and not model.currency:
                    model.currency = currency

    model.evidence = evidence
    return model, evidence
