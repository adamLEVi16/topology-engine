"""Hiring activity — the cheapest public proxy for whether a business is growing."""

from __future__ import annotations

import re
from typing import Any

from urllib.parse import urljoin, urlparse

from ..fetch import make_soup
from ..models import ROLE_CAREERS, Evidence, Page
from . import structured as st

# Hosted ATS links are the most reliable way to count real, open postings.
ATS_HOSTS = re.compile(
    r"(greenhouse\.io|lever\.co|ashbyhq\.com|workable\.com|breezy\.hr|bamboohr\.com|"
    r"recruitee\.com|teamtailor\.com|smartrecruiters\.com|jobvite\.com|workday(jobs)?\.com|"
    r"personio\.de|join\.com|rippling\.com)",
    re.I,
)

DEPARTMENTS: dict[str, tuple[str, ...]] = {
    "Engineering": ("engineer", "developer", "sre", "devops", "backend", "frontend", "full stack", "platform"),
    "Product": ("product manager", "product owner", "product lead"),
    "Design": ("designer", "ux", "ui ", "creative"),
    "Sales": ("sales", "account executive", "business development", "revenue"),
    "Marketing": ("marketing", "growth", "content", "seo", "brand"),
    "Customer Success": ("customer success", "support", "account manager", "onboarding"),
    "Operations": ("operations", "logistics", "supply", "office manager"),
    "Finance / Legal": ("finance", "accountant", "controller", "legal", "counsel"),
    "People": ("recruiter", "people ops", "hr ", "talent"),
}

NO_OPENINGS = re.compile(
    r"\b(no (current(ly)? )?(open (roles|positions|jobs)|openings|vacancies)|"
    r"we(?:'| a)?re not (currently )?hiring|check back|no positions available)\b",
    re.I,
)

APPLY_LINE = re.compile(r"\b(apply now|apply|view (job|role|position)|see (job|role))\b", re.I)

# Navigation labels, not job titles.
SECTION_INDEX = re.compile(
    r"\s*(careers?|jobs?|open (jobs?|roles?|positions?)|openings?|vacancies|"
    r"work (with us|here)|join (us|the team)|all (jobs?|roles?|openings?)|"
    r"current (openings?|vacancies)|life at \w+|browse (jobs?|roles?))\s*",
    re.I,
)


def _count_postings(page: Page) -> tuple[int, list[str], str]:
    """Return (count, role titles, how it was counted)."""
    postings = st.of_type(st.json_ld_objects(page.html), "JobPosting")
    if postings:
        titles = [st.text_of(p.get("title")) for p in postings]
        return len(postings), [t for t in titles if t], "JobPosting structured data"

    soup = make_soup(page.html)
    titles: list[str] = []
    seen: set[str] = set()
    own_path = (urlparse(page.final_url or page.url).path or "/").rstrip("/").lower()

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        text = " ".join(anchor.get_text(" ").split())
        looks_like_posting = bool(ATS_HOSTS.search(href)) or bool(
            re.search(r"/(jobs?|careers?|positions?|openings?|vacanc)", href, re.I)
            and len(text) > 3
        )
        if not looks_like_posting:
            continue
        if not text or len(text) > 90 or APPLY_LINE.fullmatch(text.lower()):
            continue

        # Every careers page has a nav bar linking to itself and to sibling
        # sections. Counting those turned "no open positions" into "2 open
        # roles", with the nav labels printed as job titles.
        target = (urlparse(urljoin(page.final_url or page.url, href)).path or "/").rstrip("/")
        if target.lower() in (own_path, ""):
            continue
        if SECTION_INDEX.fullmatch(text.lower()):
            continue

        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        titles.append(text)

    if titles:
        return len(titles), titles, "links to individual postings"
    return 0, [], ""


def extract(pages: list[Page]) -> tuple[dict[str, Any], list[Evidence]]:
    careers = st.pages_by_role(pages, ROLE_CAREERS)
    data: dict[str, Any] = {"open_roles": None, "hiring_departments": [], "role_titles": []}
    evidence: list[Evidence] = []

    if not careers:
        return data, evidence

    best_count = 0
    best_titles: list[str] = []
    best_page: Page | None = None
    best_method = ""
    saw_explicit_none = False

    for page in careers:
        if NO_OPENINGS.search(page.text):
            saw_explicit_none = True
        count, titles, method = _count_postings(page)
        if count > best_count:
            best_count, best_titles, best_page, best_method = count, titles, page, method

    # A department index in the nav is not a vacancy. When the page says there
    # are none and the "count" rests on a link or two, believe the sentence.
    if saw_explicit_none and best_count < 2:
        best_count = 0

    if best_count and best_page:
        data["open_roles"] = best_count
        data["role_titles"] = best_titles[:15]
        evidence.append(
            Evidence(
                "momentum.open_roles",
                str(best_count),
                best_page.final_url,
                "heuristic" if "links" in best_method else "json-ld",
                0.8 if "structured" in best_method else 0.55,
                snippet=f"counted via {best_method}: " + "; ".join(best_titles[:5]),
            )
        )
        blob = " ".join(best_titles).lower()
        data["hiring_departments"] = [
            dept for dept, words in DEPARTMENTS.items() if any(w in blob for w in words)
        ]
    elif saw_explicit_none:
        data["open_roles"] = 0
        evidence.append(
            Evidence("momentum.open_roles", "0", careers[0].final_url, "regex", 0.7,
                     snippet="careers page states there are no open roles")
        )

    return data, evidence
