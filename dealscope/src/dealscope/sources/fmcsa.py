"""FMCSA SAFER — the federal record of a motor carrier.

For a route or fleet business this is the single most valuable public source
there is. ``Power Units`` is a hard count of trucks, filed with the federal
government, which is a far better measure of size than anything a homepage
would claim. It also exists for businesses that have no website at all.

Two things govern the design:

* **Matching is the risk, not fetching.** Attaching the wrong carrier's crash
  history to a company would be worse than returning nothing, so a match must
  clear a similarity threshold *and* be clearly better than the runner-up.
  Anything else is reported as "no confident match".
* **Everything is cited.** Each field carries the SAFER URL it came from.

SAFER is public, serves no robots.txt, and needs no key. Requests still go
through the project's rate-limited fetcher.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from difflib import SequenceMatcher
from typing import Any

from ..fetch import make_soup
from ..models import Evidence

log = logging.getLogger("dealscope.fmcsa")

BASE = "https://safer.fmcsa.dot.gov"
SNAPSHOT_URL = BASE + "/query.asp?searchtype=ANY&query_type=queryCarrierSnapshot&query_param=USDOT&query_string={usdot}"
SEARCH_URL = BASE + "/query.asp"

# Legal-form noise that says nothing about which company this is.
NAME_NOISE = {
    "llc", "l l c", "inc", "incorporated", "corp", "corporation", "co",
    "company", "ltd", "limited", "lp", "llp", "pllc", "plc", "the", "and",
    "of", "a", "dba", "enterprises", "enterprise", "group", "holdings",
}

# A match has to be this good before we will attach a federal record to a
# company, and this much better than the next candidate.
MIN_NAME_SIMILARITY = 0.62
MIN_TOTAL_SCORE = 0.70
MIN_MARGIN = 0.06

US_STATES = re.compile(r",\s*([A-Z]{2})\s+\d{5}")


@dataclass
class Carrier:
    """One SAFER record."""

    usdot: str = ""
    legal_name: str = ""
    dba_name: str = ""
    entity_type: str = ""
    operating_status: str = ""
    operating_authority: str = ""
    out_of_service_date: str = ""
    power_units: int | None = None
    drivers: int | None = None
    inspections: int | None = None
    crashes: int | None = None
    out_of_service_pct: str = ""
    national_average_pct: str = ""
    physical_address: str = ""
    phone: str = ""
    state: str = ""
    mcs150_date: date | None = None
    mcs150_mileage: str = ""
    operation_classification: str = ""
    cargo_carried: str = ""

    # How we decided this record belongs to the company being analyzed.
    match_score: float = 0.0
    match_basis: str = ""
    considered: int = 0
    source_url: str = ""
    evidence: list[Evidence] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        return self.dba_name or self.legal_name

    @property
    def how_found(self) -> str:
        """How this record came to be attached to the brief.

        A lookup by USDOT number has no match score to report — a number is an
        identity, so there was nothing to match and nothing to get wrong.
        Printing "matched at 0%" for it read as a failed match.
        """
        if not self.match_basis:
            return "looked up directly by USDOT number — no name matching involved"
        return (
            f"{self.match_score:.0%} — {self.match_basis}; "
            f"{self.considered} candidate(s) considered"
        )

    @property
    def is_active(self) -> bool:
        # Exact compare: "ACTIVE" is a substring of "INACTIVE", which is the
        # literal value SAFER writes for a deregistered carrier.
        status = (self.operating_status or "").strip().upper()
        return status == "ACTIVE" and not self.out_of_service_date


# --- name handling ---------------------------------------------------------


def normalize_name(value: str) -> str:
    """Strip punctuation and legal-form words so names can be compared."""
    lowered = (value or "").lower()
    # Collapse dotted abbreviations first: "L.L.C." would otherwise survive
    # punctuation stripping as three single letters and never match the noise
    # list.
    lowered = re.sub(
        r"\b(?:[a-z]\.){2,}", lambda m: m.group(0).replace(".", ""), lowered
    )
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", lowered)
    tokens = [t for t in cleaned.split() if t and t not in NAME_NOISE and len(t) > 1]
    return " ".join(tokens)


# Words that describe an industry rather than identify a company. A name that
# reduces to one of these alone ("A-1 Trucking" -> "trucking") would otherwise
# score 1.0 against every carrier that does the same.
GENERIC_TOKENS = {
    "trucking", "transport", "transportation", "logistics", "hauling", "moving",
    "movers", "freight", "express", "carrier", "carriers", "delivery", "courier",
    "services", "service", "solutions", "systems", "industries", "contracting",
    "construction", "plumbing", "heating", "cooling", "landscaping", "roofing",
    "electric", "electrical", "cleaning", "maintenance", "repair",
}


def name_similarity(a: str, b: str) -> float:
    left, right = normalize_name(a), normalize_name(b)
    if not left or not right:
        return 0.0

    left_tokens, right_tokens = set(left.split()), set(right.split())

    # Checked before the equality short-circuit: two companies both reducing to
    # "trucking" are not the same company, they are both hauliers.
    if (len(left_tokens) == 1 and left_tokens <= GENERIC_TOKENS) or (
        len(right_tokens) == 1 and right_tokens <= GENERIC_TOKENS
    ):
        return 0.0

    if left == right:
        return 1.0

    shared = left_tokens & right_tokens
    union = left_tokens | right_tokens
    jaccard = len(shared) / len(union) if union else 0.0

    # A genuine shortening is a strong match. The common case is a brand name
    # against a legal entity — "Kettlewind" vs "KETTLEWIND TRANSPORT INC" — so
    # the shorter side is usually one word. Requiring two words made that
    # unmatchable; requiring a distinctive word instead still excludes short
    # coincidences like "Dot" inside "Alpha Dot".
    if shared and (left_tokens <= right_tokens or right_tokens <= left_tokens):
        if len(min(left, right, key=len)) >= 4:
            return max(0.85, jaccard)

    # Character similarity on its own is fooled by shared word endings:
    # "ace movers" scores 0.87 against "palace movers", which would attach a
    # stranger's fleet and crash history to the wrong business. Cap it by how
    # much the names agree word for word.
    ratio = SequenceMatcher(None, left, right).ratio()
    return min(ratio, jaccard + 0.25)


# --- parsing ---------------------------------------------------------------


def _blank_if_none(value: str) -> str:
    """SAFER writes the literal string "None" for empty dates."""
    cleaned = (value or "").strip(" -")
    return "" if cleaned.lower() in ("none", "") else cleaned


def _to_int(value: str) -> int | None:
    digits = re.sub(r"[^\d]", "", value or "")
    return int(digits) if digits else None


def _to_date(value: str) -> date | None:
    match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", value or "")
    if not match:
        return None
    try:
        return datetime.strptime(match.group(0), "%m/%d/%Y").date()
    except ValueError:
        return None


def parse_snapshot(html: str, usdot: str = "") -> Carrier | None:
    """Turn a SAFER Company Snapshot page into a :class:`Carrier`.

    The page is a table of label/value cells, so every pair is read into a
    dict first and fields are picked from it. That survives SAFER moving rows
    around, which it does.
    """
    soup = make_soup(html)
    fields: dict[str, str] = {}

    for label_cell in soup.find_all("th"):
        label = " ".join(label_cell.get_text(" ").split()).rstrip(":").strip()
        if not label:
            continue
        value_cell = label_cell.find_next_sibling("td")
        if value_cell is None:
            continue
        value = " ".join(value_cell.get_text(" ").split()).replace("\xa0", " ").strip()
        if label not in fields:
            fields[label] = value

    if not fields.get("Legal Name") and not fields.get("USDOT Number"):
        return None

    carrier = Carrier(
        usdot=fields.get("USDOT Number", usdot).strip() or usdot,
        legal_name=fields.get("Legal Name", "").strip(),
        dba_name=fields.get("DBA Name", "").strip(),
        entity_type=fields.get("Entity Type", "").strip(),
        # SAFER labels this "USDOT Status", not "Operating Status".
        operating_status=fields.get("USDOT Status", "").strip(),
        operating_authority=fields.get("Operating Authority Status", "").split("*")[0].strip(),
        out_of_service_date=_blank_if_none(fields.get("Out of Service Date", "")),
        power_units=_to_int(fields.get("Power Units", "")),
        drivers=_to_int(fields.get("Drivers", "")),
        inspections=_to_int(fields.get("Inspections", "")),
        crashes=_to_int(fields.get("Crashes", "")),
        out_of_service_pct=fields.get("Out of Service %", "").strip(),
        national_average_pct=next(
            (v.strip() for k, v in fields.items() if k.startswith("Nat'l Average")), ""
        ),
        physical_address=fields.get("Physical Address", "").strip(),
        phone=fields.get("Phone", "").strip(),
        mcs150_date=_to_date(fields.get("MCS-150 Form Date", "")),
        mcs150_mileage=fields.get("MCS-150 Mileage (Year)", "").strip(),
        operation_classification=fields.get("Operation Classification", "").strip(),
        cargo_carried=fields.get("Cargo Carried", "").strip(),
    )

    state = US_STATES.search(carrier.physical_address)
    if state:
        carrier.state = state.group(1)

    carrier.source_url = SNAPSHOT_URL.format(usdot=carrier.usdot)
    return carrier


def parse_search_results(html: str, limit: int = 12) -> list[str]:
    """USDOT numbers from a SAFER name-search page, in the order listed."""
    found: list[str] = []
    for match in re.finditer(r"query_string=(\d{4,9})", html):
        usdot = match.group(1)
        if usdot not in found:
            found.append(usdot)
        if len(found) >= limit:
            break
    return found


# --- lookup ----------------------------------------------------------------


def search_by_name(fetcher: Any, name: str, limit: int = 12) -> list[str]:
    """Candidate USDOT numbers for a company name. Name search needs a POST."""
    page = fetcher.post(
        SEARCH_URL,
        {
            "searchtype": "ANY",
            "query_type": "queryCarrierSnapshot",
            "query_param": "NAME",
            "query_string": name,
        },
        role="fmcsa-search",
    )
    if not page.ok:
        log.info("SAFER name search failed for %r: %s", name, page.error)
        return []
    # A single exact hit redirects straight to that carrier's snapshot.
    if "Power Units" in page.html:
        carrier = parse_snapshot(page.html)
        return [carrier.usdot] if carrier and carrier.usdot else []
    return parse_search_results(page.html, limit)


def get_snapshot(fetcher: Any, usdot: str) -> Carrier | None:
    page = fetcher.get(SNAPSHOT_URL.format(usdot=usdot), role="fmcsa")
    if not page.ok:
        return None
    return parse_snapshot(page.html, usdot)


# SAFER serves a page titled "RECORD INACTIVE" for a number that once existed
# and no longer has live authority. That is a finding. A number that returns
# nothing at all is not — see below.
_INACTIVE_PAGE = re.compile(r"RECORD\s+INACTIVE", re.I)


def get_snapshot_with_note(fetcher: Any, usdot: str) -> tuple[Carrier | None, str]:
    """The carrier record, or an explanation of why there isn't one.

    The three outcomes are genuinely different and a buyer needs them kept
    apart. An inactive record means the operating authority is dead — ask what
    happened. An empty result means nothing at all: vehicles under 10,001 lbs
    GVWR are not required to hold a USDOT number, so plenty of legitimate P&D
    fleets running Sprinter-class vans have no SAFER record. Reporting that as
    a red flag would be inventing a finding out of an absence.
    """
    page = fetcher.get(SNAPSHOT_URL.format(usdot=usdot), role="fmcsa")
    if not page.ok:
        return None, (
            f"the FMCSA register could not be reached for USDOT {usdot} "
            f"({page.error or page.status})"
        )
    carrier = parse_snapshot(page.html, usdot)
    if carrier is not None:
        return carrier, ""
    if _INACTIVE_PAGE.search(page.html or ""):
        return None, (
            f"USDOT {usdot} exists but SAFER reports the record as inactive — "
            "the operating authority is not live. Ask the seller what happened "
            "to it and under whose authority the routes run today."
        )
    return None, (
        f"no FMCSA record was returned for USDOT {usdot}. Absence is not "
        "itself a finding: vehicles under 10,001 lbs GVWR are not required to "
        "hold a USDOT number, so a van-only fleet legitimately has no record."
    )


def score_match(carrier: Carrier, name: str, state: str = "", city: str = "") -> tuple[float, str]:
    """How confident are we that this SAFER record is the company we mean?"""
    best_name = max(
        name_similarity(name, carrier.legal_name),
        name_similarity(name, carrier.dba_name),
    )
    score = best_name * 0.8
    reasons = [f"name similarity {best_name:.2f}"]

    if state and carrier.state:
        if state.upper() == carrier.state.upper():
            score += 0.15
            reasons.append(f"state matches ({carrier.state})")
        else:
            score -= 0.25
            reasons.append(f"state differs (looked for {state}, found {carrier.state})")

    if city and city.lower() in carrier.physical_address.lower():
        score += 0.10
        reasons.append(f"city matches ({city})")

    return max(0.0, min(1.0, score)), "; ".join(reasons)


def find_carrier(
    fetcher: Any,
    name: str,
    state: str = "",
    city: str = "",
    max_candidates: int = 6,
) -> tuple[Carrier | None, str]:
    """Best-matching SAFER record for a company, or ``(None, reason)``.

    Returns nothing rather than a guess. A wrong carrier attached to a business
    would put another company's fleet size and crash history into the brief,
    which is worse than an empty section.
    """
    if not name.strip():
        return None, "no company name to search with"

    candidates = search_by_name(fetcher, name)
    if not candidates:
        return None, f"no FMCSA record found matching “{name}”"

    scored: list[tuple[float, str, Carrier]] = []
    for usdot in candidates[:max_candidates]:
        carrier = get_snapshot(fetcher, usdot)
        if carrier is None:
            continue
        score, basis = score_match(carrier, name, state, city)
        scored.append((score, basis, carrier))

    if not scored:
        return None, "FMCSA returned candidates but none could be read"

    scored.sort(key=lambda item: -item[0])
    best_score, basis, best = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0

    best_name_sim = max(
        name_similarity(name, best.legal_name), name_similarity(name, best.dba_name)
    )
    if best_name_sim < MIN_NAME_SIMILARITY or best_score < MIN_TOTAL_SCORE:
        return None, (
            f"closest FMCSA record was “{best.display_name}” (USDOT {best.usdot}), "
            f"too weak a match to rely on ({basis})"
        )
    if len(scored) > 1 and (best_score - runner_up) < MIN_MARGIN:
        return None, (
            f"several FMCSA records match “{name}” about equally well "
            f"(closest: {best.display_name}, USDOT {best.usdot}); "
            "not attaching one without a stronger signal"
        )

    best.match_score = round(best_score, 2)
    best.match_basis = basis
    best.considered = len(scored)
    best.evidence = build_evidence(best)
    return best, ""


def build_evidence(carrier: Carrier) -> list[Evidence]:
    """One record per field, all pointing at the SAFER snapshot."""
    url = carrier.source_url
    items: list[Evidence] = [
        Evidence(
            "fleet.usdot",
            f"USDOT {carrier.usdot} — {carrier.display_name}",
            url,
            "fmcsa",
            carrier.match_score,
            snippet=f"matched on {carrier.match_basis}",
        )
    ]

    def add(field_name: str, value: Any, confidence: float = 0.95) -> None:
        if value not in (None, "", "--"):
            items.append(Evidence(field_name, str(value), url, "fmcsa", confidence))

    add("fleet.power_units", carrier.power_units)
    add("fleet.drivers", carrier.drivers)
    add("fleet.operating_status", carrier.operating_status)
    add("fleet.operating_authority", carrier.operating_authority)
    add("fleet.out_of_service_date", carrier.out_of_service_date)
    add("fleet.inspections", carrier.inspections, 0.9)
    add("fleet.crashes", carrier.crashes, 0.9)
    add("fleet.out_of_service_pct", carrier.out_of_service_pct, 0.9)
    add("fleet.entity_type", carrier.entity_type)
    add("fleet.physical_address", carrier.physical_address, 0.9)
    add("fleet.phone", carrier.phone, 0.9)
    add("fleet.mcs150_date", carrier.mcs150_date.isoformat() if carrier.mcs150_date else None, 0.9)
    add("fleet.cargo_carried", carrier.cargo_carried, 0.85)
    return items
