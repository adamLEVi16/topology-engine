"""Who is this company, and what do they say they do?"""

from __future__ import annotations

import re
from typing import Any

from ..fetch import make_soup
from ..models import ROLE_ABOUT, ROLE_HOME, ROLE_PRODUCT, Evidence, Page
from . import structured as st

# Coarse sector labels. These are descriptive hints for a reader, not a
# taxonomy — a buyer uses them to orient, not to file the company.
INDUSTRY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "SaaS / software": ("saas", "software platform", "cloud platform", "web app", "our software"),
    "Developer tools": ("api", "sdk", "developer", "open source", "ci/cd", "devops", "self-host"),
    "E-commerce / retail": (
        "free shipping", "add to cart", "shop now", "our store", "returns policy",
        "shop all", "your cart", "in stock", "sold out", "size guide", "checkout",
    ),
    "Marketing / advertising": ("marketing", "advertising", "campaign", "seo", "brand strategy"),
    "Fintech / payments": ("payments", "fintech", "banking", "invoicing", "payouts", "lending"),
    "Healthcare": ("patient", "clinical", "healthcare", "hipaa", "telehealth", "medical"),
    "Education": ("students", "curriculum", "courses", "learning platform", "classroom"),
    "Professional services": ("consulting", "our clients", "engagement", "advisory", "we partner with"),
    "Agency": ("agency", "creative studio", "we design", "branding", "our portfolio"),
    "Real estate": ("property", "listings", "real estate", "tenants", "leasing"),
    "Logistics": ("shipping", "freight", "supply chain", "warehouse", "fulfilment", "fulfillment"),
    "Manufacturing": ("manufacturing", "factory", "production line", "oem", "industrial"),
    "Hospitality / food": ("restaurant", "menu", "reservations", "hotel", "guests", "catering"),
    "Analytics / data": ("analytics", "dashboards", "data warehouse", "business intelligence", "metrics"),
    "Security": ("cybersecurity", "threat", "vulnerability", "endpoint", "zero trust"),
    "AI / ML": ("machine learning", "artificial intelligence", " llm", "neural", "ai-powered"),
    "Nonprofit": ("donate", "nonprofit", "501(c)(3)", "our mission is to", "charity"),
}

_SEPARATORS = re.compile(r"\s[|–—\-·:>]+\s")
_BOILERPLATE = re.compile(
    r"^(home|welcome|homepage|official site|official website|untitled)$", re.I
)
_FOUNDED = re.compile(
    r"\b(?:founded|established|est\.?|started|launched|since|serving\s+\w+\s+since)"
    r"\s*(?:in\s+)?(19\d{2}|20[0-2]\d)\b",
    re.I,
)


def domain_root(domain: str) -> str:
    label = domain[4:] if domain.startswith("www.") else domain
    return label.split(".")[0]


def _name_from_title(title: str, domain: str) -> str:
    """Pull the brand out of a page title like ``Acme | Widgets for teams``."""
    segments = [s.strip() for s in _SEPARATORS.split(title) if s.strip()]
    if not segments:
        return ""
    root = re.sub(r"[^a-z0-9]", "", domain_root(domain).lower())

    # Prefer whichever segment actually looks like the domain's brand.
    if root:
        for segment in segments:
            if re.sub(r"[^a-z0-9]", "", segment.lower()).startswith(root):
                return segment

    first = segments[0]
    if _BOILERPLATE.match(first) and len(segments) > 1:
        first = segments[1]
    # A long first segment is a slogan, not a name.
    return first if len(first) <= 60 else ""


def _org_objects(pages: list[Page]) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for page in pages:
        if page.ok:
            objects.extend(st.json_ld_objects(page.html))
    return st.of_type(
        objects, "Organization", "Corporation", "LocalBusiness", "OnlineBusiness", "WebSite"
    )


def _first_paragraph(page: Page, min_len: int = 120) -> str:
    soup = make_soup(page.html)
    for tag in soup.find_all(["p", "h2"]):
        text = " ".join(tag.get_text(" ").split())
        if len(text) >= min_len:
            return text
    return ""


def extract(pages: list[Page], domain: str) -> tuple[dict[str, Any], list[Evidence]]:
    home = next((p for p in pages if p.role == ROLE_HOME and p.ok), None)
    about_pages = st.pages_by_role(pages, ROLE_ABOUT)
    evidence: list[Evidence] = []
    data: dict[str, Any] = {
        "name": "",
        "tagline": "",
        "description": "",
        "industry_tags": [],
        "founded_year": None,
        "canonical_url": (home.final_url if home else f"https://{domain}/"),
    }

    metas = st.meta_tags(home.html) if home else {}
    orgs = _org_objects(pages)

    # --- name ---
    for org in orgs:
        name = st.text_of(org.get("name"))
        if name and len(name) <= 80:
            data["name"] = name
            evidence.append(
                Evidence("identity.name", name, data["canonical_url"], "json-ld", 0.95)
            )
            break

    if not data["name"] and metas.get("og:site_name"):
        data["name"] = metas["og:site_name"]
        evidence.append(
            Evidence("identity.name", data["name"], data["canonical_url"], "meta", 0.85)
        )

    if not data["name"] and metas.get("application-name"):
        data["name"] = metas["application-name"]
        evidence.append(
            Evidence("identity.name", data["name"], data["canonical_url"], "meta", 0.8)
        )

    if not data["name"] and home:
        guess = _name_from_title(home.title or metas.get("title", ""), domain)
        if guess:
            data["name"] = guess
            evidence.append(
                Evidence("identity.name", guess, data["canonical_url"], "heuristic", 0.6,
                         snippet=home.title)
            )

    if not data["name"]:
        data["name"] = domain_root(domain).replace("-", " ").title()
        evidence.append(
            Evidence("identity.name", data["name"], data["canonical_url"], "heuristic", 0.3,
                     snippet="derived from the domain name")
        )

    # --- tagline: the one-line value proposition, usually the hero heading ---
    if home:
        soup = make_soup(home.html)
        h1 = soup.find("h1")
        if h1:
            text = " ".join(h1.get_text(" ").split())
            if 8 <= len(text) <= 140 and text.lower() != data["name"].lower():
                data["tagline"] = text
                evidence.append(
                    Evidence("identity.tagline", text, home.final_url, "heuristic", 0.7)
                )

    if not data["tagline"]:
        candidate = metas.get("og:description") or metas.get("description") or ""
        if 8 <= len(candidate) <= 160:
            data["tagline"] = candidate
            evidence.append(
                Evidence("identity.tagline", candidate, data["canonical_url"], "meta", 0.6)
            )

    # --- description ---
    for key, method, conf in (
        ("description", "meta", 0.8),
        ("og:description", "meta", 0.75),
    ):
        value = metas.get(key)
        if value and len(value) >= 40:
            data["description"] = value
            evidence.append(
                Evidence("identity.description", value, data["canonical_url"], method, conf)
            )
            break

    if not data["description"]:
        for org in orgs:
            value = st.text_of(org.get("description"))
            if len(value) >= 40:
                data["description"] = value
                evidence.append(
                    Evidence("identity.description", value, data["canonical_url"], "json-ld", 0.9)
                )
                break

    if not data["description"]:
        for page in about_pages or ([home] if home else []):
            para = _first_paragraph(page)
            if para:
                data["description"] = para
                evidence.append(
                    Evidence("identity.description", para[:300], page.final_url, "heuristic", 0.55)
                )
                break

    # --- founded year ---
    for org in orgs:
        raw = st.text_of(org.get("foundingDate"))
        match = re.search(r"(19\d{2}|20[0-2]\d)", raw)
        if match:
            data["founded_year"] = int(match.group(1))
            evidence.append(
                Evidence("scale.founded_year", match.group(1), data["canonical_url"], "json-ld", 0.9)
            )
            break

    if data["founded_year"] is None:
        for page in about_pages + ([home] if home else []):
            match = _FOUNDED.search(page.text)
            if match:
                data["founded_year"] = int(match.group(1))
                start = max(0, match.start() - 60)
                evidence.append(
                    Evidence(
                        "scale.founded_year", match.group(1), page.final_url, "regex", 0.65,
                        snippet=page.text[start : match.end() + 40].replace("\n", " "),
                    )
                )
                break

    # --- industry tags ---
    corpus = st.joined_text(
        st.pages_by_role(pages, ROLE_HOME, ROLE_ABOUT, ROLE_PRODUCT), 40_000
    ).lower()
    hits: list[tuple[str, int]] = []
    for label, keywords in INDUSTRY_KEYWORDS.items():
        count = sum(corpus.count(word) for word in keywords)
        # One stray keyword is noise; a sector should show up repeatedly.
        if count >= 2:
            hits.append((label, count))
    hits.sort(key=lambda kv: -kv[1])
    data["industry_tags"] = [label for label, _ in hits[:3]]
    if data["industry_tags"]:
        evidence.append(
            Evidence(
                "identity.industry",
                ", ".join(data["industry_tags"]),
                data["canonical_url"],
                "heuristic",
                0.45,
                snippet="inferred from recurring vocabulary on the site",
            )
        )

    return data, evidence
