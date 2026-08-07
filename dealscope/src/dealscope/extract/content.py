"""Publishing cadence, site freshness, and funding or ownership mentions.

Is anyone still home? A site whose newest post is three years old and whose
footer still says 2021 tells a buyer something important before a single
financial statement changes hands.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any

from ..fetch import make_soup
from ..models import ROLE_ABOUT, ROLE_BLOG, ROLE_HOME, Evidence, Page
from . import structured as st

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

ISO_DATE = re.compile(r"\b(20\d{2})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b")
MONTH_FIRST = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2}),?\s+(20\d{2})\b",
    re.I,
)
DAY_FIRST = re.compile(
    r"\b(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?,?\s+(20\d{2})\b",
    re.I,
)
COPYRIGHT = re.compile(r"(?:©|&copy;|copyright)\s*(?:\d{4}\s*[–\-—]\s*)?(20\d{2})", re.I)

FUNDING = re.compile(
    r"\b(?:raised|raising|closed|secured)\s+(?:a\s+|an\s+)?"
    r"(?:\$|€|£)?[\d.]+\s*(?:million|billion|m\b|bn\b|k\b)?[^.\n]{0,40}"
    r"|\bseries\s+[a-e]\b(?:\s+round)?"
    r"|\b(?:seed|pre-seed)\s+(?:round|funding|investment)\b"
    r"|\bbacked by\s+[A-Z][^.\n]{0,50}"
    r"|\b(?:acquired by|acquisition by|merged with)\s+[A-Z][^.\n]{0,50}"
    r"|\b(?:y ?combinator|techstars)\b(?:\s+\(?[WS]\d{2}\)?)?",
    re.I,
)

BOOTSTRAPPED = re.compile(
    r"\b(bootstrapped|self-funded|profitable since|no outside (funding|investors)|"
    r"independently owned|family[- ]owned|employee[- ]owned)\b",
    re.I,
)


def _valid(year: int, month: int, day: int, today: date) -> date | None:
    try:
        parsed = date(year, month, day)
    except ValueError:
        return None
    if parsed > today or parsed.year < 2000:
        return None
    return parsed


def parse_dates(text: str, today: date | None = None) -> list[date]:
    """Every plausible publication date in a blob of text."""
    today = today or datetime.now(timezone.utc).date()
    found: list[date] = []

    for match in ISO_DATE.finditer(text):
        parsed = _valid(int(match.group(1)), int(match.group(2)), int(match.group(3)), today)
        if parsed:
            found.append(parsed)

    for match in MONTH_FIRST.finditer(text):
        parsed = _valid(
            int(match.group(3)), MONTHS[match.group(1).lower()[:3]], int(match.group(2)), today
        )
        if parsed:
            found.append(parsed)

    for match in DAY_FIRST.finditer(text):
        parsed = _valid(
            int(match.group(3)), MONTHS[match.group(2).lower()[:3]], int(match.group(1)), today
        )
        if parsed:
            found.append(parsed)

    return found


def _dates_from_markup(page: Page, today: date) -> list[date]:
    """Machine-readable dates: <time datetime>, article meta, JSON-LD."""
    found: list[date] = []
    soup = make_soup(page.html)

    for tag in soup.find_all("time"):
        value = tag.get("datetime") or tag.get_text(" ", strip=True)
        found.extend(parse_dates(value or "", today))

    metas = st.meta_tags(page.html)
    for key in ("article:published_time", "article:modified_time", "og:updated_time"):
        if metas.get(key):
            found.extend(parse_dates(metas[key], today))

    for obj in st.of_type(
        st.json_ld_objects(page.html), "BlogPosting", "Article", "NewsArticle", "WebPage"
    ):
        for key in ("datePublished", "dateModified"):
            value = st.text_of(obj.get(key))
            if value:
                found.extend(parse_dates(value, today))

    return found


def extract(
    pages: list[Page], window_days: int, today: date | None = None
) -> tuple[dict[str, Any], list[Evidence]]:
    today = today or datetime.now(timezone.utc).date()
    blog_pages = st.pages_by_role(pages, ROLE_BLOG)
    all_ok = [p for p in pages if p.ok]
    home_url = next((p.final_url for p in pages if p.role == ROLE_HOME and p.ok), "")

    evidence: list[Evidence] = []
    data: dict[str, Any] = {
        "last_content_date": None,
        "posts_per_month": None,
        "content_window_days": window_days,
        "copyright_year": None,
        "funding_mentions": [],
        "ownership_notes": [],
    }

    # --- publication dates ---
    dates: list[date] = []
    source_url = ""
    for page in blog_pages:
        page_dates = _dates_from_markup(page, today) or parse_dates(page.text, today)
        if page_dates:
            dates.extend(page_dates)
            source_url = source_url or page.final_url

    if dates:
        dates.sort()
        newest = dates[-1]
        data["last_content_date"] = newest
        evidence.append(
            Evidence(
                "momentum.last_post",
                newest.isoformat(),
                source_url,
                "heuristic",
                0.7,
                snippet=f"newest of {len(dates)} dated items on the blog index",
            )
        )

        recent = [d for d in dates if (today - d).days <= window_days]
        if len(recent) >= 2:
            span_days = max((recent[-1] - recent[0]).days, 28)
            data["posts_per_month"] = round(len(recent) / (span_days / 30.44), 1)
            evidence.append(
                Evidence(
                    "momentum.cadence",
                    f"{data['posts_per_month']}/month",
                    source_url,
                    "heuristic",
                    0.55,
                    snippet=f"{len(recent)} posts across {span_days} days",
                )
            )
        elif recent:
            data["posts_per_month"] = round(len(recent) / (window_days / 30.44), 1)

    # --- footer copyright year ---
    years: list[tuple[int, str]] = []
    for page in all_ok:
        for match in COPYRIGHT.finditer(page.text[-4000:] or page.text):
            years.append((int(match.group(1)), page.final_url))
    if years:
        year, url = max(years, key=lambda t: t[0])
        data["copyright_year"] = year
        evidence.append(Evidence("momentum.copyright_year", str(year), url, "regex", 0.7))

    # --- funding / ownership ---
    # Read only pages where a company talks about itself. A publication's blog
    # is full of other companies' funding rounds, and reading those as its own
    # produced "the site mentions backed by state actors".
    own_voice = st.pages_by_role(pages, ROLE_HOME, ROLE_ABOUT)
    seen: set[str] = set()
    for page in own_voice:
        if len(data["funding_mentions"]) >= 5:
            break
        for match in FUNDING.finditer(page.text):
            phrase = " ".join(match.group(0).split())[:120]
            key = phrase.lower()
            if key in seen:
                continue
            seen.add(key)
            data["funding_mentions"].append(phrase)
            evidence.append(
                Evidence(
                    "momentum.funding",
                    phrase,
                    page.final_url,  # the page it was actually found on
                    "regex",
                    0.45,
                    snippet="mentioned on the site; not verified against a filing",
                )
            )
            if len(data["funding_mentions"]) >= 5:
                break

    for page in own_voice:
        for match in BOOTSTRAPPED.finditer(page.text):
            phrase = " ".join(match.group(0).split())
            if phrase.lower() not in {n.lower() for n in data["ownership_notes"]}:
                data["ownership_notes"].append(phrase)
                evidence.append(
                    Evidence("momentum.ownership", phrase, page.final_url, "regex", 0.5)
                )
        if len(data["ownership_notes"]) >= 3:
            break

    return data, evidence
