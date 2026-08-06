"""Contact surface, social presence, legal pages, and compliance claims.

Together these make up how reachable and how accountable a business looks —
the "transparency" side of the brief. A company with no address, no named
people, and no terms of service is not necessarily a bad buy, but it is a
different diligence problem than one with all three.
"""

from __future__ import annotations

import re
from typing import Any

from ..fetch import make_soup
from ..models import (
    ROLE_ABOUT,
    ROLE_CONTACT,
    ROLE_HOME,
    ROLE_LEGAL,
    ROLE_SECURITY,
    Evidence,
    Page,
)
from . import structured as st

SOCIAL_PATTERNS: dict[str, str] = {
    "LinkedIn": r"linkedin\.com/(company|in|school)/[\w\-%.]+",
    "X / Twitter": r"(twitter|x)\.com/[\w]{2,20}",
    "Facebook": r"facebook\.com/[\w\-.]{2,50}",
    "Instagram": r"instagram\.com/[\w\-.]{2,40}",
    "YouTube": r"youtube\.com/(@[\w\-.]+|c/[\w\-.]+|channel/[\w\-]+|user/[\w\-.]+)",
    "GitHub": r"github\.com/[\w\-.]{2,40}",
    "TikTok": r"tiktok\.com/@[\w\-.]{2,40}",
    "Crunchbase": r"crunchbase\.com/organization/[\w\-]+",
    "Discord": r"discord\.(gg|com/invite)/[\w\-]+",
    "Mastodon": r"[\w.]+/@[\w]+@[\w.]+",
    "Bluesky": r"bsky\.app/profile/[\w\-.]+",
}

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]{2,}")
TEL_LINK = re.compile(r"tel:\+?[\d\s().\-]{6,}", re.I)
PHONE_TEXT = re.compile(
    r"(?:\+\d{1,3}[\s.\-]?)?(?:\(\d{2,4}\)[\s.\-]?|\d{2,4}[\s.\-])\d{3,4}[\s.\-]?\d{3,4}\b"
)
US_ADDRESS = re.compile(
    r"\d{1,6}\s+[\w.'\-]+(?:\s+[\w.'\-]+){0,4}\s+"
    r"(street|st|avenue|ave|road|rd|boulevard|blvd|drive|dr|lane|ln|way|suite|ste|floor|fl)\b"
    r"[^\n]{0,60}",
    re.I,
)

# What a local trade business publishes instead of SOC 2: where it works, when
# it is open, and whether it is licensed. These are its real credibility signals.
SERVICE_AREA = re.compile(
    r"\b(?:serving|proudly serving|service(?:s)? (?:area|areas)|areas we serve|"
    r"we serve|serving the)\s*:?\s*(?P<area>[A-Z][\w.'\-]*(?:[ ,&/]+(?:and\s+)?[A-Z][\w.'\-]*){0,8})",
)
HOURS = re.compile(
    r"\b(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?\s*[-–—to]{1,3}\s*"
    r"(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?[^\n]{0,30}?"
    r"\d{1,2}(?::\d{2})?\s*(?:am|pm)[^\n]{0,20}",
    re.I,
)
ALWAYS_OPEN = re.compile(r"\b(24[/ ]?7|24 hours a day|open 24 hours|around the clock)\b", re.I)

LOCAL_CREDENTIALS: dict[str, str] = {
    "Licensed & insured": r"\blicen[cs]ed\s*(?:and|&)\s*insured\b",
    "Bonded & insured": r"\bbonded\s*(?:and|&)\s*insured\b",
    "Fully insured": r"\bfully insured\b",
    "State licence number published": r"\b(?:lic(?:ense|ence)?\.?\s*(?:no\.?|#|number)\s*[:.]?\s*[A-Z]{0,3}[- ]?\d{4,})",
    "BBB accredited": r"\bbbb\s*(?:accredited|a\+|rating)\b",
    "EPA certified": r"\bepa\s*(?:certified|certification)\b",
    "NATE certified": r"\bnate[- ]certified\b",
    "Certified arborist": r"\bcertified arborists?\b",
}

COMPLIANCE: dict[str, str] = {
    "SOC 2": r"\bsoc\s?-?\s?2\b",
    "ISO 27001": r"\biso[\s/-]?27001\b",
    "GDPR": r"\bgdpr\b",
    "HIPAA": r"\bhipaa\b",
    "PCI DSS": r"\bpci[\s-]?dss\b",
    "CCPA": r"\bccpa\b",
    "FedRAMP": r"\bfedramp\b",
    "Cyber Essentials": r"\bcyber essentials\b",
    "ISO 9001": r"\biso[\s/-]?9001\b",
}

# Addresses of mail providers, not of the company.
GENERIC_EMAIL_HOST = re.compile(r"@(example|sentry|wixpress|squarespace|godaddy|domain)\b", re.I)
IMAGE_EMAIL = re.compile(r"\.(png|jpe?g|gif|svg|webp|css|js)$", re.I)


def _clean_phone(value: str) -> str:
    return " ".join(re.sub(r"[^\d+()\-.\s]", "", value).split())


def _addresses_from_jsonld(pages: list[Page]) -> tuple[list[str], list[str], list[Evidence]]:
    addresses: list[str] = []
    locations: list[str] = []
    evidence: list[Evidence] = []

    for page in pages:
        objects = st.json_ld_objects(page.html)
        for obj in objects:
            raw = obj.get("address")
            candidates = raw if isinstance(raw, list) else [raw]
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                parts = [
                    st.text_of(candidate.get(key))
                    for key in (
                        "streetAddress",
                        "addressLocality",
                        "addressRegion",
                        "postalCode",
                        "addressCountry",
                    )
                ]
                formatted = ", ".join(p for p in parts if p)
                if formatted and formatted not in addresses:
                    addresses.append(formatted)
                    evidence.append(
                        Evidence("trust.address", formatted, page.final_url, "json-ld", 0.9)
                    )
                locality = st.text_of(candidate.get("addressLocality"))
                region = st.text_of(candidate.get("addressCountry")) or st.text_of(
                    candidate.get("addressRegion")
                )
                place = ", ".join(p for p in (locality, region) if p)
                if place and place not in locations:
                    locations.append(place)

    return addresses, locations, evidence


def extract(pages: list[Page], domain: str) -> tuple[dict[str, Any], list[Evidence]]:
    contact_pages = st.pages_by_role(pages, ROLE_CONTACT, ROLE_ABOUT, ROLE_HOME)
    all_ok = [p for p in pages if p.ok]
    evidence: list[Evidence] = []
    data: dict[str, Any] = {
        "emails": [],
        "phones": [],
        "addresses": [],
        "locations": [],
        "socials": {},
        "legal_pages": {},
        "compliance_claims": [],
        "service_areas": [],
        "opening_hours": "",
    }

    # --- socials (scan every page: they usually live in the footer) ---
    for page in all_ok:
        soup = make_soup(page.html)
        hrefs = [a["href"] for a in soup.find_all("a", href=True)]
        for network, pattern in SOCIAL_PATTERNS.items():
            if network in data["socials"]:
                continue
            for href in hrefs:
                match = re.search(pattern, href, re.I)
                if match:
                    url = match.group(0)
                    if not url.startswith("http"):
                        url = "https://" + url
                    data["socials"][network] = url
                    evidence.append(
                        Evidence("trust.social", f"{network}: {url}", page.final_url, "link", 0.85)
                    )
                    break

    # --- emails ---
    seen_emails: set[str] = set()
    for page in contact_pages or all_ok[:3]:
        soup = make_soup(page.html)
        candidates = [
            a["href"][7:].split("?")[0]
            for a in soup.find_all("a", href=True)
            if a["href"].lower().startswith("mailto:")
        ]
        candidates += EMAIL.findall(page.text)
        for address in candidates:
            address = address.strip().lower()
            if (
                not address
                or address in seen_emails
                or IMAGE_EMAIL.search(address)
                or GENERIC_EMAIL_HOST.search(address)
                or len(address) > 80
            ):
                continue
            seen_emails.add(address)
            data["emails"].append(address)
            evidence.append(Evidence("trust.email", address, page.final_url, "link", 0.85))
            if len(data["emails"]) >= 6:
                break
        if len(data["emails"]) >= 6:
            break

    # --- phones (tel: links are trustworthy; loose text matching is not) ---
    seen_phones: set[str] = set()
    for page in contact_pages or all_ok[:3]:
        soup = make_soup(page.html)
        for anchor in soup.find_all("a", href=TEL_LINK):
            number = _clean_phone(anchor["href"][4:])
            if number and number not in seen_phones:
                seen_phones.add(number)
                data["phones"].append(number)
                evidence.append(Evidence("trust.phone", number, page.final_url, "link", 0.9))
        if not data["phones"] and page.role == ROLE_CONTACT:
            match = PHONE_TEXT.search(page.text)
            if match:
                number = _clean_phone(match.group(0))
                if len(re.sub(r"\D", "", number)) >= 9:
                    seen_phones.add(number)
                    data["phones"].append(number)
                    evidence.append(
                        Evidence("trust.phone", number, page.final_url, "regex", 0.5)
                    )
        if len(data["phones"]) >= 4:
            break

    # --- addresses ---
    addresses, locations, address_evidence = _addresses_from_jsonld(all_ok)
    data["addresses"] = addresses[:4]
    data["locations"] = locations[:4]
    evidence.extend(address_evidence)

    if not data["addresses"]:
        for page in contact_pages:
            match = US_ADDRESS.search(page.text)
            if match:
                formatted = " ".join(match.group(0).split())
                data["addresses"] = [formatted]
                evidence.append(
                    Evidence("trust.address", formatted, page.final_url, "regex", 0.5)
                )
                break

    # --- legal + security pages ---
    for page in st.pages_by_role(pages, ROLE_LEGAL, ROLE_SECURITY):
        label = page.title.split("|")[0].strip() or page.role.title()
        data["legal_pages"][label[:60]] = page.final_url
        evidence.append(
            Evidence("trust.legal_page", label[:60], page.final_url, "link", 0.9)
        )

    # --- service areas, hours, and local credentials ---
    corpus = st.joined_text(all_ok, 120_000)

    areas: list[str] = []
    for match in SERVICE_AREA.finditer(corpus):
        area = " ".join(match.group("area").split()).strip(" ,&/")
        # "Serving Since" and similar sentence fragments are not places.
        if len(area) < 3 or area.lower() in ("since", "you", "our", "the", "all", "we"):
            continue
        if area.lower() not in {a.lower() for a in areas}:
            areas.append(area)
        if len(areas) >= 4:
            break
    if areas:
        data["service_areas"] = areas
        source = next(
            (p.final_url for p in all_ok if SERVICE_AREA.search(p.text)), all_ok[0].final_url
        )
        evidence.append(
            Evidence("scale.service_area", "; ".join(areas), source, "regex", 0.55)
        )

    hours_match = HOURS.search(corpus)
    if hours_match:
        data["opening_hours"] = " ".join(hours_match.group(0).split())[:120]
    elif ALWAYS_OPEN.search(corpus):
        data["opening_hours"] = "advertises 24/7 availability"
    if data["opening_hours"]:
        source = next(
            (p.final_url for p in all_ok if HOURS.search(p.text) or ALWAYS_OPEN.search(p.text)),
            all_ok[0].final_url,
        )
        evidence.append(
            Evidence("trust.hours", data["opening_hours"], source, "regex", 0.6)
        )

    for label, pattern in LOCAL_CREDENTIALS.items():
        match = re.search(pattern, corpus, re.I)
        if match:
            data["compliance_claims"].append(label)
            source = next(
                (p.final_url for p in all_ok if re.search(pattern, p.text, re.I)),
                all_ok[0].final_url if all_ok else "",
            )
            evidence.append(
                Evidence("trust.credential", label, source, "regex", 0.5,
                         snippet=f"claimed on the site: “{match.group(0)[:60]}”")
            )

    # --- compliance claims ---
    for label, pattern in COMPLIANCE.items():
        match = re.search(pattern, corpus, re.I)
        if match:
            data["compliance_claims"].append(label)
            source = next(
                (
                    p.final_url
                    for p in all_ok
                    if re.search(pattern, p.text, re.I)
                ),
                all_ok[0].final_url if all_ok else "",
            )
            evidence.append(
                Evidence(
                    "trust.compliance",
                    label,
                    source,
                    "regex",
                    0.5,
                    snippet="claimed on the site; not independently verified",
                )
            )

    return data, evidence
