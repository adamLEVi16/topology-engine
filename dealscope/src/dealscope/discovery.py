"""Decide which pages on a site are worth reading.

A homepage alone rarely answers a buyer's questions. The pages that do —
pricing, about, team, careers, customers, legal — are found by classifying
navigation links, falling back to the sitemap when navigation is rendered
client-side, and finally probing a short list of conventional paths.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from .config import Config
from .fetch import Fetcher, clean_url, make_soup, same_site
from .models import (
    ROLE_ABOUT,
    ROLE_BLOG,
    ROLE_CAREERS,
    ROLE_CONTACT,
    ROLE_CUSTOMERS,
    ROLE_LEGAL,
    ROLE_PRICING,
    ROLE_PRODUCT,
    ROLE_SECURITY,
    ROLE_TEAM,
    Page,
)

# role -> (url path patterns, anchor text patterns, conventional paths to probe)
ROLE_RULES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    ROLE_PRICING: (
        r"/(pricing|plans?|price|packages|subscribe|buy|quote)(/|$|\.)",
        r"^\s*(pricing|plans|price|packages|buy now|get a quote)\s*$",
        ("/pricing", "/plans", "/pricing/"),
    ),
    ROLE_ABOUT: (
        r"/(about|about-us|company|our-story|who-we-are|mission|overview)(/|$|\.)",
        r"^\s*(about|about us|our story|company|who we are|our mission)\s*$",
        ("/about", "/about-us", "/company"),
    ),
    ROLE_PRODUCT: (
        r"/(products?|features?|solutions?|platform|services?|what-we-do|how-it-works)(/|$|\.)",
        r"^\s*(product|products|features|solutions|platform|services|how it works)\s*$",
        ("/product", "/features", "/services"),
    ),
    ROLE_TEAM: (
        r"/(team|our-team|leadership|people|management|founders|staff|about/team)(/|$|\.)",
        r"^\s*(team|our team|leadership|meet the team|people|founders|management)\s*$",
        ("/team", "/about/team", "/leadership"),
    ),
    ROLE_CUSTOMERS: (
        r"/(customers?|clients?|case-stud(y|ies)|testimonials?|success-stories|portfolio|work)(/|$|\.)",
        r"^\s*(customers|clients|case studies|testimonials|success stories|our work|portfolio)\s*$",
        ("/customers", "/case-studies", "/clients"),
    ),
    ROLE_CAREERS: (
        r"/(careers?|jobs?|join-?us|work-with-us|hiring|open-positions|vacancies|opportunities)(/|$|\.)",
        r"^\s*(careers|jobs|join us|we're hiring|were hiring|work with us|open roles|open positions)\s*$",
        ("/careers", "/jobs", "/careers/"),
    ),
    ROLE_CONTACT: (
        r"/(contact|contact-us|get-in-touch|reach-us|support|help)(/|$|\.)",
        r"^\s*(contact|contact us|get in touch|support|help)\s*$",
        ("/contact", "/contact-us"),
    ),
    ROLE_BLOG: (
        r"/(blog|news|articles?|insights?|press|updates?|resources?|stories|changelog|newsroom)(/|$|\.)",
        r"^\s*(blog|news|articles|insights|press|resources|updates|newsroom|changelog)\s*$",
        ("/blog", "/news", "/blog/"),
    ),
    ROLE_SECURITY: (
        r"/(security|trust|compliance|soc-?2|gdpr|privacy-and-security)(/|$|\.)",
        r"^\s*(security|trust|trust center|compliance)\s*$",
        ("/security", "/trust"),
    ),
    ROLE_LEGAL: (
        r"/(privacy|terms|legal|tos|eula|cookie|imprint|impressum|disclaimer)(/|$|\.|-)",
        r"^\s*(privacy|privacy policy|terms|terms of service|terms & conditions|legal|imprint|cookie policy)\s*$",
        # Includes the paths Shopify and other hosted platforms use, since
        # those sites often render their footer client-side.
        (
            "/privacy", "/terms", "/privacy-policy", "/terms-of-service",
            "/policies/privacy-policy", "/pages/privacy-policy", "/legal",
        ),
    ),
}

# Links that never help and often cost a request.
SKIP_URL = re.compile(
    r"(/(login|log-in|signin|sign-in|signup|sign-up|register|cart|checkout|account|admin|"
    r"search|feed|rss|sitemap|wp-admin|wp-login|api|cdn-cgi)(/|$|\?))"
    r"|\.(pdf|jpe?g|png|gif|svg|webp|zip|gz|mp4|mp3|css|js|ico|woff2?|xml|json|dmg|exe|pkg)($|\?)",
    re.I,
)
# Localised duplicates of pages we already have (/es/pricing, /fr-fr/about ...).
SKIP_LOCALE = re.compile(r"^/([a-z]{2}(-[a-z]{2})?)/", re.I)
_KNOWN_TLD_LIKE = {"js", "io", "co", "ai", "app", "dev", "me", "tv", "in", "it", "de", "us"}


def _norm_text(value: str) -> str:
    return " ".join((value or "").split()).lower()


def classify(url: str, anchor: str) -> tuple[str | None, float]:
    """Guess a page role from its URL and link text.

    URL matches outrank anchor-text matches: a link labelled "Learn more" that
    points at ``/pricing`` is a pricing page, and a nav item reading "Pricing"
    that points at ``/`` is not.
    """
    path = urlparse(url).path or "/"
    text = _norm_text(anchor)
    best: tuple[str | None, float] = (None, 0.0)

    for role, (url_pat, text_pat, _) in ROLE_RULES.items():
        score = 0.0
        if re.search(url_pat, path, re.I):
            score = 3.0
            # A short path is likelier to be the section index than a deep leaf.
            depth = len([p for p in path.split("/") if p])
            score -= min(depth - 1, 3) * 0.4
        if text and re.search(text_pat, text, re.I):
            score += 2.0
        elif text and role.replace("_", " ") in text:
            score += 0.5
        if score > best[1]:
            best = (role, score)

    return best


def links_from(page: Page, domain: str) -> list[tuple[str, str]]:
    """Same-site (url, anchor text) pairs from a page, de-duplicated."""
    if not page.ok:
        return []
    soup = make_soup(page.html)
    base = page.final_url or page.url
    seen: set[str] = set()
    out: list[tuple[str, str]] = []

    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        url = clean_url(href, base)
        if not url or url in seen or not same_site(url, domain):
            continue
        if SKIP_URL.search(urlparse(url).path or ""):
            continue
        seen.add(url)
        out.append((url, tag.get_text(" ", strip=True)))

    return out


def _sitemap_candidates(fetcher: Fetcher, home_url: str, domain: str, limit: int = 600) -> list[str]:
    """URLs listed in the site's sitemap(s), following one level of index."""
    # robots.txt can name any sitemap URL at all, including an internal
    # address. Only the site's own sitemaps are followed.
    declared = [u for u in fetcher.sitemap_urls(home_url) if same_site(u, domain)]
    roots = declared or [
        f"{urlparse(home_url).scheme}://{urlparse(home_url).netloc}/sitemap.xml"
    ]
    found: list[str] = []
    visited: set[str] = set()
    queue = list(roots[:3])

    while queue and len(found) < limit:
        target = queue.pop(0)
        if target in visited:
            continue
        visited.add(target)
        body = fetcher.get_text(target)
        if not body:
            continue
        locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", body, re.I)
        is_index = "<sitemapindex" in body[:2000].lower()
        for loc in locs:
            url = clean_url(loc)
            if not url or not same_site(url, domain):
                continue
            if is_index:
                if len(visited) + len(queue) < 5:
                    queue.append(url)
            elif not SKIP_URL.search(urlparse(url).path or ""):
                found.append(url)
                if len(found) >= limit:
                    break

    return found


def _looks_localised(url: str, known_paths: set[str] | None = None) -> bool:
    """Is this a locale-prefixed duplicate of a page we already have?

    Only when the un-prefixed twin is in the link set. A site served entirely
    under /en/ has no twin — dropping those links left it with no navigation
    at all and a brief that reported no pricing, about, careers or contact
    page for a site that publishes every one of them.
    """
    path = urlparse(url).path or "/"
    match = SKIP_LOCALE.match(path)
    if not match or match.group(1).lower() in _KNOWN_TLD_LIKE:
        return False
    if known_paths is None:
        return True
    twin = "/" + path[match.end():]
    return twin.rstrip("/") in known_paths or twin in known_paths


# Roles where a second page genuinely adds information: privacy *and* terms,
# a careers index *and* a posting, several case studies.
MULTI_PAGE_ROLES = (ROLE_LEGAL, ROLE_PRODUCT, ROLE_CAREERS, ROLE_CUSTOMERS)

# Hosted platforms put standard pages at predictable paths. Knowing the
# platform from the homepage markup turns a blind guess into a good one, which
# matters most on sites whose footer is assembled in the browser.
PLATFORM_PATHS: dict[str, dict[str, tuple[str, ...]]] = {
    "Shopify": {
        # Shopify's default robots.txt disallows /policies/, so the /pages/
        # equivalents — which stores routinely publish — are tried first.
        ROLE_LEGAL: (
            "/pages/privacy-policy",
            "/pages/terms-of-service",
            "/pages/terms-of-use",
            "/policies/privacy-policy",
            "/policies/terms-of-service",
        ),
        ROLE_ABOUT: ("/pages/about", "/pages/about-us", "/pages/our-story"),
        ROLE_CONTACT: ("/pages/contact", "/pages/contact-us"),
        ROLE_CAREERS: ("/pages/careers",),
        ROLE_BLOG: ("/blogs/news",),
    },
    "WordPress": {
        ROLE_LEGAL: ("/privacy-policy", "/terms-of-service", "/terms-and-conditions"),
        ROLE_ABOUT: ("/about-us",),
        ROLE_CONTACT: ("/contact-us",),
    },
    "WooCommerce": {
        ROLE_LEGAL: ("/privacy-policy", "/terms-and-conditions"),
    },
    "Squarespace": {
        ROLE_LEGAL: ("/privacy", "/terms"),
        ROLE_ABOUT: ("/about",),
    },
    "Webflow": {
        ROLE_LEGAL: ("/privacy-policy", "/terms-of-service"),
    },
    "Ghost": {
        ROLE_LEGAL: ("/privacy", "/terms"),
        ROLE_ABOUT: ("/about",),
    },
}


@dataclass(frozen=True)
class Candidate:
    """A URL we might fetch for a given role.

    ``linked`` distinguishes a URL the site itself pointed at from one we
    guessed. It matters after the fetch: a linked page that 404s is a broken
    link worth reporting, while a guess that 404s is simply a guess that missed
    and should stay out of the brief.
    """

    url: str
    role: str
    score: float
    linked: bool


def plan_candidates(
    fetcher: Fetcher,
    home: Page,
    domain: str,
    config: Config,
    platform_hints: tuple[str, ...] = (),
) -> dict[str, list[Candidate]]:
    """Rank fetch candidates per role, best first.

    Several candidates per role is deliberate. Sites restructure, and a link
    labelled "Pricing" can point at a path that no longer resolves; the caller
    walks the list until something actually loads.
    """
    scored: dict[str, dict[str, tuple[float, bool]]] = {}
    home_links = links_from(home, domain)
    known_paths = {(urlparse(u).path or "/").rstrip("/") or "/" for u, _ in home_links}

    def record(url: str, role: str, score: float, linked: bool) -> None:
        bucket = scored.setdefault(role, {})
        previous = bucket.get(url)
        if previous is None or score > previous[0]:
            bucket[url] = (score, linked or (previous[1] if previous else False))

    def offer(url: str, anchor: str, penalty: float = 0.0, linked: bool = True) -> None:
        if _looks_localised(url, known_paths):
            return
        role, score = classify(url, anchor)
        if not role or score <= 0:
            return
        record(url, role, score - penalty, linked)

        # A link to /jobs/customer-success means a /jobs index probably exists,
        # and the index is worth more to a buyer than one posting. Offer it as a
        # guess — both slash forms, since strict static hosts serve only one.
        parts = urlparse(url)
        segments = [seg for seg in parts.path.split("/") if seg]
        for depth in range(1, len(segments)):
            stem = "/" + "/".join(segments[:depth])
            anc_role, anc_score = classify(stem + "/", "")
            if anc_role != role or anc_score <= 0:
                continue
            for variant in (stem + "/", stem):
                ancestor = clean_url(f"{parts.scheme}://{parts.netloc}{variant}")
                if ancestor:
                    record(ancestor, role, anc_score - penalty - 0.1, False)

    home_url = home.final_url or home.url
    for url, anchor in home_links:
        offer(url, anchor)

    # Sitemap entries carry no anchor text, so they score lower by design and
    # only matter for roles navigation gave us nothing for.
    missing = [role for role in ROLE_RULES if role not in scored]
    if missing and home.ok:
        for url in _sitemap_candidates(fetcher, home_url, domain):
            role, score = classify(url, "")
            if role in missing and score > 0:
                offer(url, "", penalty=0.5)

    # Paths the detected platform is known to use. Ranked above blind guesses
    # but below anything the site actually linked to.
    for platform in platform_hints:
        for role, paths in PLATFORM_PATHS.get(platform, {}).items():
            for position, path in enumerate(paths):
                candidate = clean_url(path, home_url)
                if candidate and candidate != home_url:
                    record(candidate, role, 1.0 - position * 0.01, False)

    # Conventional paths, always offered as last-resort guesses. They rescue
    # sites whose navigation only exists once JavaScript has run. The order
    # inside ROLE_RULES is meaningful, so preserve it rather than sorting.
    for role, (_url_pat, _text_pat, probes) in ROLE_RULES.items():
        for position, probe in enumerate(probes):
            candidate = clean_url(probe, home_url)
            if candidate and candidate != home_url:
                record(candidate, role, 0.2 - position * 0.01, False)

    ranked: dict[str, list[Candidate]] = {}
    for role, bucket in scored.items():
        entries = [
            Candidate(url, role, score, linked)
            for url, (score, linked) in bucket.items()
            if url != home_url
        ]
        # Prefer high scores, then site-declared URLs, then shorter paths.
        entries.sort(key=lambda c: (-c.score, not c.linked, len(c.url)))
        ranked[role] = entries[: 6 if role == ROLE_LEGAL else 4]

    return {role: ranked[role] for role in ROLE_RULES if ranked.get(role)}


def extra_candidates(
    pages: list[Page], domain: str, roles: set[str], exclude: set[str]
) -> dict[str, list[Candidate]]:
    """Candidates for ``roles`` found on pages other than the homepage.

    Sites often link a team page only from ``/about``, or case studies only
    from a product page. Once the first wave has been read, re-scanning what
    came back recovers those without spending a request.
    """
    scored: dict[str, dict[str, tuple[float, bool]]] = {}

    for page in pages:
        links = links_from(page, domain)
        known_paths = {(urlparse(u).path or "/").rstrip("/") or "/" for u, _ in links}
        for url, anchor in links:
            if url in exclude or _looks_localised(url, known_paths):
                continue
            role, score = classify(url, anchor)
            if role not in roles or score <= 0:
                continue
            bucket = scored.setdefault(role, {})
            if score > bucket.get(url, (float("-inf"), False))[0]:
                bucket[url] = (score, True)

    ranked: dict[str, list[Candidate]] = {}
    for role, bucket in scored.items():
        entries = [Candidate(url, role, score, linked) for url, (score, linked) in bucket.items()]
        entries.sort(key=lambda c: (-c.score, len(c.url)))
        ranked[role] = entries[:3]
    return ranked


def plan(fetcher: Fetcher, home: Page, domain: str, config: Config) -> list[tuple[str, str]]:
    """Flat ``(url, role)`` list using the top candidate per role.

    Convenience wrapper for callers that do not want to drive the fallback
    loop themselves; the analyzer uses :func:`plan_candidates` directly.
    """
    budget = max(1, config.max_pages - 1)  # the homepage is already spent
    selected: list[tuple[str, str]] = []
    for role, candidates in plan_candidates(fetcher, home, domain, config).items():
        keep = 2 if role in MULTI_PAGE_ROLES else 1
        for candidate in candidates[:keep]:
            selected.append((candidate.url, candidate.role))
    return selected[:budget]
