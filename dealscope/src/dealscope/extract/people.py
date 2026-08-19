"""Team size, leadership, and named customers.

For a small-business acquisition these are proxies for two things a buyer
badly wants to know: how many people the operation actually takes, and how
concentrated the customer base looks.
"""

from __future__ import annotations

import re
from typing import Any

from ..fetch import make_soup
from ..models import (
    ROLE_ABOUT,
    ROLE_CUSTOMERS,
    ROLE_HOME,
    ROLE_TEAM,
    Evidence,
    Page,
)
from . import structured as st

# One name token, used everywhere a name is matched — roster lines and prose
# alike. Previously each site had its own character class and they disagreed:
# the prose patterns allowed no apostrophe in the first position and neither
# allowed an accent anywhere, so O'Brien, Ruiz-Díaz and Søren were silently
# dropped from the roster while Smith was kept.
#
# Python's re has no \p{Lu}, so the Latin-1 letter ranges are spelled out. The
# token must contain at least one lowercase letter, which is what stops an
# ALLCAPS heading ("ABOUT US") from reading as a person.
_UP = "A-ZÀ-ÖØ-Þ"
_LO = "a-zà-öø-ÿ"
_NAME_TOKEN = rf"[{_UP}][{_UP}{_LO}'’\-]{{0,19}}[{_LO}][{_UP}{_LO}'’\-]{{0,10}}"
_INITIAL = rf"[{_UP}]\.?"

NAME_LINE = re.compile(rf"^{_NAME_TOKEN}(?:\s+(?:{_NAME_TOKEN}|{_INITIAL})){{1,2}}$")

TITLE_LINE = re.compile(
    r"\b(ceo|cto|coo|cfo|cmo|cpo|cio|founder|co-?founder|owner|principal|partner|president|"
    r"managing director|director|head of|vp\b|vice president|chief \w+|lead\b|manager|engineer|"
    r"developer|designer|architect|analyst|consultant|advisor|scientist|marketer|recruiter|"
    r"account executive|customer success|support|operations)\b",
    re.I,
)

EXEC_TITLE = re.compile(
    r"\b(ceo|cto|coo|cfo|cmo|cpo|cio|chief \w+|founder|co-?founder|owner|president|"
    r"managing director|managing partner|vp\b|vice president|head of)\b",
    re.I,
)

# Lines that pass the "two capitalised words" test but are never people.
NOT_A_NAME = re.compile(
    r"\b(privacy|policy|terms|service|contact|about|home|blog|news|pricing|log ?in|sign ?up|"
    r"cookie|copyright|all rights|read more|learn more|case study|get started|our team|"
    r"meet the|follow us|social media|united states|new york|san francisco|los angeles|"
    r"customer|support|solutions?|products?|features?|company|careers?|jobs?)\b",
    re.I,
)

# Title-cased legal boilerplate ("Owner or Authorized User is the owner of…")
# reads exactly like a name followed by a job title. Requiring every token to
# be a plausible name word is what keeps that out of the roster.
NAME_STOPWORDS = {
    "a", "all", "an", "and", "any", "are", "as", "at", "authorized", "be", "best",
    "by", "client", "clients", "company", "content", "customer", "customers",
    "each", "exclusive", "for", "free", "from", "group", "has", "have", "in",
    "inc", "is", "it", "its", "limited", "llc", "ltd", "may", "more", "must",
    "new", "no", "not", "of", "on", "or", "other", "our", "owner", "policy",
    "privacy", "product", "products", "provider", "service", "services", "shall",
    "site", "such", "team", "terms", "that", "the", "their", "these", "this",
    "to", "use", "used", "user", "users", "using", "we", "website", "will",
    "with", "you", "your",
}


# Whose name a buyer needs first. Lower sorts earlier.
_SENIORITY = (
    (re.compile(r"\b(founder|co-?founder|owner|ceo|chief executive)\b", re.I), 0),
    (re.compile(r"\b(president|managing (director|partner))\b", re.I), 1),
    (re.compile(r"\b(c[toifpm]o|chief \w+)\b", re.I), 2),
    (re.compile(r"\b(vp|vice president)\b", re.I), 3),
    (re.compile(r"\bhead of\b", re.I), 4),
    (re.compile(r"\bdirector\b", re.I), 5),
)


def _seniority(title: str) -> int:
    for pattern, rank in _SENIORITY:
        if pattern.search(title or ""):
            return rank
    return 9


def _plausible_name(name: str) -> bool:
    tokens = [t.strip(".,'’-").lower() for t in name.split()]
    if not (2 <= len(tokens) <= 3):
        return False
    return not any(token in NAME_STOPWORDS for token in tokens)


# The number must be matched whole, at both ends. Guarding only the start let
# "a team of 1,200" read as a headcount of 1; guarding the end too strictly
# broke "a team of 18, based in Bristol". So: thousands separators are part of
# the number, and a trailing comma only disqualifies when digits follow it.
# The second alternative also needs an ownership phrase — "serving 4,500
# people" is a customer count, not a headcount.
_COUNT = r"(?<![\d,.])(\d{1,3}(?:,\d{3})+|\d{1,5})(?!\d|,\d)"
_APPROX = r"(?:about\s+|around\s+|over\s+|more than\s+|nearly\s+)?"

# Things a business can be "a family of" that are not employees. "A family of
# four restaurants" read as a headcount of four. A positive list of person
# nouns cannot do this job here: it would also throw away "a team of 18, based
# in Bristol", which names no noun at all, and "a team of 30 designers", whose
# noun no closed list will ever contain. So the guard names the collectives
# that are countable *things*, and everything else is still allowed through.
_NOT_PEOPLE = (
    r"restaurants?|brands?|companies|businesses|stores?|shops?|locations?|"
    r"products?|offices?|sites?|websites?|hotels?|clinics?|practices?|"
    r"publications?|titles?|apps?|services?|communities|blogs?|newsletters?|"
    r"podcasts?|projects?|labels?|studios?|franchises?|dealerships?|branches?|"
    r"outlets?|brands|properties|vehicles?|trucks?|stores"
)
_PERSON_NOUN = (
    r"employees|people|staff|team members|professionals|engineers|designers|"
    r"developers|consultants|technicians|specialists|advisors|advisers|experts|"
    r"contractors|craftspeople|colleagues"
)

HEADCOUNT = re.compile(
    rf"\b(?:team of|we(?:'| a)?re a? ?team of|staff of|group of|family of|company of)\s+"
    rf"{_APPROX}{_COUNT}\b(?!\s+(?:{_NOT_PEOPLE})\b)"
    rf"|\b(?:we (?:have|employ)|employing|with a team of|our team of)\s+"
    rf"{_APPROX}{_COUNT}\+?\s+"
    rf"(?:{_PERSON_NOUN})\b",
    re.I,
)

TRUSTED_BY = re.compile(
    r"\b(trusted by|used by|powering|join(ed)? (over|more than)?|loved by|serving)\s+"
    r"(?:over\s+|more than\s+|about\s+)?([\d,]+(?:,\d{3})*\+?)\s+"
    # Any plural noun: sites count "customers", "clinics", "stores", "schools".
    r"([a-z]{3,20}s)\b",
    re.I,
)

GENERIC_ALT = re.compile(
    r"^(logo|image|icon|arrow|avatar|photo|picture|banner|hero|background|placeholder|star|"
    r"quote|check|menu|close|search|cart|profile|thumbnail|illustration|graphic)s?\b",
    re.I,
)


def _people_from_jsonld(pages: list[Page]) -> tuple[list[dict[str, str]], list[Evidence]]:
    people: list[dict[str, str]] = []
    evidence: list[Evidence] = []
    for page in pages:
        for person in st.of_type(st.json_ld_objects(page.html), "Person"):
            name = st.text_of(person.get("name"))
            title = st.text_of(person.get("jobTitle")) or st.text_of(person.get("description"))
            if name and len(name) <= 60:
                people.append({"name": name, "title": title})
                evidence.append(
                    Evidence(
                        "scale.person",
                        f"{name}{' — ' + title if title else ''}",
                        page.final_url,
                        "json-ld",
                        0.9,
                    )
                )
    return people, evidence


CUSTOMER_CONTEXT = re.compile(
    r"(customers?|clients?|trusted by|used by|works? with|partners?|brands?|"
    r"case stud|testimonial|as seen (in|on)|featured (in|on)|our work)",
    re.I,
)

# The tail of a job title that names a different organisation. A testimonial is
# always attributed this way — "Practice Owner, Riverside Clinic" — and that
# person works for the customer, not for the business being valued.
ORG_TAIL = re.compile(
    r"\b(inc|llc|ltd|limited|corp|corporation|co|company|group|holdings|partners|"
    r"associates|clinic|clinics|practice|practices|hospital|health|medical|dental|"
    r"studio|studios|agency|salon|spa|bank|school|academy|university|college|"
    r"church|restaurant|cafe|brewery|motors|automotive|logistics|transport|"
    r"trucking|construction|contracting|realty|properties|solutions|systems|"
    r"labs|technologies|software|media|foundation|institute|society|association)\b",
    re.I,
)

# Headings that introduce testimonials, anchored and spelled out in full.
#
# A loose vocabulary here is dangerous in one direction only: a false positive
# deletes real people, and the brief then reports the company as smaller than
# it is — or as naming nobody at all. Bare "customers", "clients" and "our
# work" matched "Customer Success" (a department) and "Our Work" (a portfolio),
# emptying the rosters of the companies that had them. Failing the other way
# only means a testimonial byline occasionally survives, which the
# other-organisation check still catches.
CUSTOMER_HEADING = re.compile(
    r"^(?:"
    r"what (?:our |their )?(?:clients?|customers?|people|partners?) say"
    r"|(?:client|customer|success)[ -]stor(?:y|ies)"
    r"|(?:client|customer) (?:testimonials?|reviews?|voices)"
    r"|testimonials?"
    r"|case stud(?:y|ies)"
    r"|trusted by"
    r"|reviews?"
    r"|in their own words"
    r"|as seen (?:in|on)"
    r"|featured (?:in|on)"
    r")\b",
    re.I,
)

_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")

# An own-name fragment shorter than this is too generic to match a title tail on.
MIN_OWN_NAME = 4


def _external_person(title: str, own_names: set[str] | None = None) -> bool:
    """Does this title attribute the person to a *different* organisation?

    Only a comma-separated tail that reads as an organisation counts, so "Head
    of Engineering, London" is a colleague with a location. And the tail must
    not be the company's own name: "CEO, Kettlewind Logistics" on Kettlewind's
    own team page is the person a buyer most needs named, not a testimonial.
    """
    if "," not in title:
        return False
    tail = title.split(",", 1)[1].strip(" .")
    if not tail or not tail[:1].isupper():
        return False
    flat = re.sub(r"[^a-z0-9]", "", tail.lower())
    # Anchored containment, not a bare substring test: matching any four-char
    # fragment anywhere let kent.com claim "Practice Owner, Kentucky Medical
    # Group" as its own staff.
    for own in own_names or ():
        if len(own) < MIN_OWN_NAME or not flat:
            continue
        if flat == own or flat.startswith(own) or own.startswith(flat):
            return False
    return bool(ORG_TAIL.search(tail))


def _customer_lines(page: Page) -> set[str]:
    """Flattened text lines sitting under a testimonial heading.

    Resolved on the DOM rather than by scanning flattened lines, because both
    cheaper approaches fail on ordinary markup. Comparing a line against the
    set of heading texts misses "What our <span>clients</span> say", whose
    flattened line never equals the heading text. And tracking "the last line
    that looked like a heading" breaks on the commonest testimonial pattern of
    all — the byline is itself a heading, so <h3>Marcus Bell</h3> closed the
    very section it sat inside and let the whole block into the roster.

    A section runs from its heading to the next heading of the same or higher
    rank, so a deeper heading inside it stays inside it.
    """
    soup = make_soup(page.html)
    blocked: set[str] = set()

    for heading in soup.find_all(_HEADING_TAGS):
        text = " ".join(heading.get_text(" ", strip=True).split())
        if not CUSTOMER_HEADING.search(text):
            continue
        rank = int(heading.name[1])
        for node in heading.find_all_next():
            name = getattr(node, "name", "")
            if name in _HEADING_TAGS and int(name[1]) <= rank:
                break
            line = " ".join(node.get_text(" ", strip=True).split())
            if line:
                blocked.add(line)
    return blocked


def _people_from_text(
    pages: list[Page], limit: int, own_names: set[str] | None = None
) -> tuple[list[dict[str, str]], list[Evidence]]:
    """Pair a name-shaped line with a job title on a nearby line.

    Requiring the title is what keeps ``Privacy Policy`` and ``San Francisco``
    out of the roster — a bare capitalised phrase is never accepted as a person.
    """
    people: list[dict[str, str]] = []
    evidence: list[Evidence] = []
    seen: set[str] = set()

    for page in pages:
        # Resolved once per page, on the DOM. Scanning the preceding lines for
        # customer wording — the first attempt at this — meant a colleague's own
        # job title ("Customer Success Lead") put the next person inside a
        # customer block and deleted them, along with everyone listed after.
        in_customer_block = _customer_lines(page)
        lines = [line.strip() for line in page.text.splitlines()]
        for index, line in enumerate(lines):
            if not NAME_LINE.match(line) or NOT_A_NAME.search(line):
                continue
            if not _plausible_name(line):
                continue
            # "Chief Executive Officer" is three capitalised words and would
            # otherwise pass as a name. A job title is never the person.
            if TITLE_LINE.search(line):
                continue
            # A name under a "What our clients say" heading is a customer.
            if " ".join(line.split()) in in_customer_block:
                continue
            for offset in (1, 2):
                if index + offset >= len(lines):
                    break
                following = lines[index + offset]
                if not following or len(following) > 80:
                    continue
                if TITLE_LINE.search(following):
                    if _external_person(following, own_names):
                        break
                    key = line.lower()
                    if key not in seen:
                        seen.add(key)
                        people.append({"name": line, "title": following})
                        evidence.append(
                            Evidence(
                                "scale.person",
                                f"{line} — {following}",
                                page.final_url,
                                "heuristic",
                                0.6,
                            )
                        )
                    break
            if len(people) >= limit:
                return people, evidence

    return people, evidence


# Small businesses rarely have a roster page — they tell their story in
# sentences. "Uku Taht started Plausible in 2018" carries exactly the
# ownership information a buyer needs, so it is worth reading prose too.
# Spaces are matched as [ \t] rather than \s throughout: \s crosses newlines,
# which would let a heading run into the sentence below it and produce names
# like "About Kettlewind Priya Raman".
_NAME = rf"(?P<name>{_NAME_TOKEN}(?:[ \t]+{_NAME_TOKEN}){{1,2}})"

FOUNDER_PROSE = re.compile(
    rf"\b{_NAME}[ \t]+(?P<verb>started|founded|co-?founded|launched|created|bootstrapped)\b"
)
IS_TITLE_PROSE = re.compile(
    rf"\b{_NAME}[ \t]*,?[ \t]+(?:is|was|as)[ \t]+(?:the[ \t]+|our[ \t]+|a[ \t]+|an[ \t]+)?"
    r"(?P<title>CEO|CTO|COO|CFO|CMO|chief [a-z ]{3,25}|co-?founder|founder|owner|"
    r"president|managing director|managing partner|head of [a-z ]{3,25})\b",
    re.I,
)
TITLE_FIRST_PROSE = re.compile(
    r"\b(?P<title>CEO|CTO|COO|CFO|CMO|co-?founder|founder|owner|president|"
    r"managing director)[ \t]+" + _NAME + r"\b",
    re.I,
)
JOINED_PROSE = re.compile(
    rf"\b{_NAME}[ \t]+joined[ \t]+(?:the[ \t]+(?:team|company)[ \t]+)?"
    r"(?:to[ \t]+(?:handle|lead|run|manage|head)[ \t]+|as[ \t]+(?:the[ \t]+|a[ \t]+|an[ \t]+)?)"
    r"(?P<title>[a-z][a-z ,&]{2,40})",
    re.I,
)

_PROSE_PATTERNS = (
    (FOUNDER_PROSE, "verb"),
    (IS_TITLE_PROSE, "title"),
    (TITLE_FIRST_PROSE, "title"),
    (JOINED_PROSE, "title"),
)


def _people_from_prose(
    pages: list[Page], exclude: set[str], limit: int
) -> tuple[list[dict[str, str]], list[Evidence]]:
    people: list[dict[str, str]] = []
    evidence: list[Evidence] = []
    seen: set[str] = set()

    for page in pages:
        for pattern, group in _PROSE_PATTERNS:
            for match in pattern.finditer(page.text):
                name = " ".join(match.group("name").split())
                key = name.lower()
                flat = re.sub(r"[^a-z0-9]", "", key)
                if key in seen or flat in exclude or NOT_A_NAME.search(name):
                    continue
                if not _plausible_name(name):
                    continue
                if group == "verb":
                    title = "Founder"
                else:
                    title = " ".join(match.group("title").split()).strip(" ,&")
                    title = title[:1].upper() + title[1:]
                    if _external_person(title, exclude):
                        continue
                seen.add(key)
                people.append({"name": name, "title": title})
                start = max(0, match.start() - 30)
                evidence.append(
                    Evidence(
                        "scale.person",
                        f"{name} — {title}",
                        page.final_url,
                        "regex",
                        0.55,
                        snippet=page.text[start : match.end() + 60].replace("\n", " "),
                    )
                )
                if len(people) >= limit:
                    return people, evidence

    return people, evidence


# Placeholder alt text on a logo wall. "Client" is a label, not a client.
PLACEHOLDER_CUSTOMER = re.compile(
    r"^(client|customer|company|brand|partner|logo|our client|case study|"
    r"testimonial|read more|learn more|view|next|previous)s?$",
    re.I,
)


def _logo_wall_images(soup, min_group: int = 3) -> set[int]:
    """Images belonging to a group of similar sibling images.

    A customer logo strip is always a row of several small images. A lone
    image with a short alt is a video thumbnail or an illustration — which is
    how "Walkthrough" ended up listed as a Basecamp customer.
    """
    accepted: set[int] = set()
    for img in soup.find_all("img", alt=True):
        node = img
        for _ in range(3):
            node = node.parent
            if node is None:
                break
            group = [
                candidate
                for candidate in node.find_all("img", alt=True)
                if len(candidate.get("alt", "").strip()) <= 40
            ]
            if len(group) >= min_group:
                accepted.update(id(candidate) for candidate in group)
                break
    return accepted


def _in_customer_context(img) -> bool:
    """Does an ancestor of this image talk about customers or clients?"""
    node = img
    for _ in range(4):
        node = node.parent
        if node is None:
            return False
        if CUSTOMER_CONTEXT.search(node.get_text(" ", strip=True)[:400]):
            return True
    return False


def _customers_from_logos(
    pages: list[Page], limit: int, exclude: set[str]
) -> tuple[list[str], list[Evidence]]:
    """Customer names from logo-wall image alt text and 'trusted by' strips."""
    names: list[str] = []
    evidence: list[Evidence] = []
    seen: set[str] = set()

    for page in pages:
        soup = make_soup(page.html)
        # A dedicated customers page is all context; elsewhere the image has to
        # earn its place by sitting in a logo wall or under customer wording.
        whole_page_is_customers = page.role == ROLE_CUSTOMERS
        wall = set() if whole_page_is_customers else _logo_wall_images(soup)

        for img in soup.find_all("img", alt=True):
            if not whole_page_is_customers and id(img) not in wall and not _in_customer_context(img):
                continue
            alt = " ".join(img["alt"].split())
            if not alt or len(alt) > 40 or GENERIC_ALT.match(alt):
                continue
            cleaned = re.sub(r"\s*(logo|logotype|icon|wordmark)\s*$", "", alt, flags=re.I).strip()
            if len(cleaned) < 2 or NOT_A_NAME.search(cleaned):
                continue
            if PLACEHOLDER_CUSTOMER.match(cleaned):
                continue
            # Logo walls are alt-tagged with bare brand names, not sentences.
            if len(cleaned.split()) > 4 or not re.match(r"^[A-Za-z0-9][\w&.,'’\- ]*$", cleaned):
                continue
            key = cleaned.lower()
            # The company's own wordmark is the most common logo on any site.
            if re.sub(r"[^a-z0-9]", "", key) in exclude:
                continue
            if key not in seen:
                seen.add(key)
                names.append(cleaned)
                evidence.append(
                    Evidence("scale.customer", cleaned, page.final_url, "heuristic", 0.5,
                             snippet=f"logo alt text: {alt}")
                )
            if len(names) >= limit:
                return names, evidence

    return names, evidence


def extract(
    pages: list[Page],
    max_people: int,
    max_customers: int,
    company_name: str = "",
    domain: str = "",
) -> tuple[dict[str, Any], list[Evidence]]:
    team_pages = st.pages_by_role(pages, ROLE_TEAM, ROLE_ABOUT)
    customer_pages = st.pages_by_role(pages, ROLE_CUSTOMERS, ROLE_HOME)
    corpus = st.joined_text(st.pages_by_role(pages, ROLE_HOME, ROLE_ABOUT, ROLE_TEAM), 60_000)
    home_url = next((p.final_url for p in pages if p.role == ROLE_HOME and p.ok), "")

    evidence: list[Evidence] = []
    data: dict[str, Any] = {
        "named_people": [],
        "leadership": [],
        "named_customers": [],
        "headcount_estimate": "",
        "headcount_basis": "",
        "customer_count_claim": "",
    }

    own_names = {
        re.sub(r"[^a-z0-9]", "", part.lower())
        for part in (company_name, domain, domain.split(".")[0] if domain else "")
        if part
    }
    own_names.discard("")

    def merge(found: list[dict[str, str]], found_evidence: list[Evidence]) -> None:
        known = {p["name"].lower() for p in people}
        for person, ev in zip(found, found_evidence):
            if person["name"].lower() not in known:
                known.add(person["name"].lower())
                people.append(person)
                people_evidence.append(ev)

    people, people_evidence = _people_from_jsonld(team_pages or pages[:1])
    if len(people) < 3:
        merge(*_people_from_text(team_pages, max_people, own_names))
    if len(people) < 3:
        merge(*_people_from_prose(team_pages, own_names, max_people))

    data["named_people"] = people[:max_people]
    # Rank by seniority, not alphabetically. Sorting by first name pushed the
    # CEO out of the summary behind two colleagues whose names start with A.
    data["leadership"] = sorted(
        (p for p in data["named_people"] if EXEC_TITLE.search(p.get("title", ""))),
        key=lambda p: _seniority(p.get("title", "")),
    )
    evidence.extend(people_evidence[:max_people])

    # --- headcount ---
    stated = HEADCOUNT.search(corpus)
    if stated:
        number = int((stated.group(1) or stated.group(2)).replace(",", ""))
        if 0 < number < 500_000:
            data["headcount_estimate"] = f"~{number}"
            data["headcount_basis"] = "stated on the site"
            evidence.append(
                Evidence("scale.headcount", f"~{number}", home_url, "regex", 0.75,
                         snippet=stated.group(0))
            )
    if not data["headcount_estimate"] and data["named_people"]:
        count = len(data["named_people"])
        bucket = "1, a solo operator" if count == 1 else f"at least {count}"
        data["headcount_estimate"] = bucket
        data["headcount_basis"] = (
            "one person is named on the site"
            if count == 1
            else f"{count} people are named on the site"
        )
        evidence.append(
            Evidence("scale.headcount", bucket, team_pages[0].final_url if team_pages else home_url,
                     "heuristic", 0.45, snippet=data["headcount_basis"])
        )

    # --- customers ---
    claim = TRUSTED_BY.search(corpus)
    if claim:
        data["customer_count_claim"] = " ".join(claim.group(0).split())
        evidence.append(
            Evidence("scale.customer_claim", data["customer_count_claim"], home_url, "regex", 0.55,
                     snippet="marketing claim, unverified")
        )

    names, customer_evidence = _customers_from_logos(
        customer_pages, max_customers, own_names
    )
    data["named_customers"] = names
    evidence.extend(customer_evidence)

    return data, evidence
