"""Core data structures for dealscope.

Everything the analyzer learns about a company flows through these types.
The guiding rule is that any fact which reaches a brief carries the URL it
came from, so a buyer can click through and check it themselves.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

__all__ = [
    "Evidence",
    "Page",
    "Signal",
    "RiskFlag",
    "TechFinding",
    "BusinessModel",
    "Scale",
    "Momentum",
    "Operations",
    "TrustProfile",
    "Score",
    "ScoreCard",
    "CompanyBrief",
    "to_jsonable",
    "ROLE_PRIORITY",
]


# --- Page roles ------------------------------------------------------------
# The kinds of page discovery knows how to recognise, ordered by how much
# they tend to tell a buyer about the business.

ROLE_HOME = "home"
ROLE_PRICING = "pricing"
ROLE_ABOUT = "about"
ROLE_PRODUCT = "product"
ROLE_TEAM = "team"
ROLE_CUSTOMERS = "customers"
ROLE_CAREERS = "careers"
ROLE_CONTACT = "contact"
ROLE_BLOG = "blog"
ROLE_SECURITY = "security"
ROLE_LEGAL = "legal"
ROLE_OTHER = "other"

ROLE_PRIORITY: tuple[str, ...] = (
    ROLE_HOME,
    ROLE_PRICING,
    ROLE_ABOUT,
    ROLE_PRODUCT,
    ROLE_TEAM,
    ROLE_CUSTOMERS,
    ROLE_CAREERS,
    ROLE_CONTACT,
    ROLE_BLOG,
    ROLE_SECURITY,
    ROLE_LEGAL,
    ROLE_OTHER,
)


# --- Evidence --------------------------------------------------------------


@dataclass(frozen=True)
class Evidence:
    """One observed fact, tied to where it was seen.

    ``method`` records how it was obtained (``json-ld``, ``meta``, ``regex``,
    ``link``, ``heuristic``) because a buyer should weigh a structured
    ``Organization`` record more heavily than a keyword match in body text.
    """

    field: str
    value: str
    source_url: str
    method: str = "heuristic"
    confidence: float = 0.5
    snippet: str = ""

    def short(self, limit: int = 160) -> str:
        text = self.snippet or self.value
        text = " ".join(text.split())
        return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


@dataclass
class Page:
    """A fetched page plus the text extracted from it."""

    url: str
    final_url: str = ""
    status: int = 0
    role: str = ROLE_OTHER
    title: str = ""
    html: str = ""
    text: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    fetched_at: datetime | None = None
    from_cache: bool = False
    rendered: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and 200 <= self.status < 300 and bool(self.html)

    def summary(self) -> dict[str, Any]:
        """Compact record for the brief's appendix (drops the page body)."""
        return {
            "url": self.final_url or self.url,
            "role": self.role,
            "status": self.status,
            "title": self.title,
            "words": len(self.text.split()),
            "rendered": self.rendered,
            "error": self.error,
        }


# --- Derived findings ------------------------------------------------------


@dataclass
class Signal:
    """An interpreted observation that feeds the scores and the narrative."""

    key: str
    label: str
    category: str  # scale | commercial | momentum | operations | trust
    detail: str = ""
    value: Any = None
    weight: float = 0.0
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class RiskFlag:
    """Something a buyer should look at before wiring money."""

    key: str
    title: str
    severity: str  # low | medium | high
    detail: str = ""
    evidence: list[Evidence] = field(default_factory=list)

    _ORDER = {"high": 0, "medium": 1, "low": 2}

    @property
    def rank(self) -> int:
        return self._ORDER.get(self.severity, 3)


@dataclass
class TechFinding:
    name: str
    category: str
    detail: str = ""
    evidence: list[Evidence] = field(default_factory=list)


def _package_version() -> str:
    """The installed version, so a brief never claims a stale one.

    Imported lazily: config imports models, so a module-level import here
    would be circular.
    """
    from .config import __version__

    return __version__


# --- Brief sections --------------------------------------------------------


@dataclass
class BusinessModel:
    primary: str = "unknown"          # saas | ecommerce | services | marketplace | media | hardware
    # How the call was reached, rather than a percentage. A share-of-total
    # number looked like a probability and was not one: it fell when a site
    # simply said more, and rose when it said little. What a reader can
    # actually check is how many distinct signals fired and what came second.
    signal_count: int = 0
    secondary: list[str] = field(default_factory=list)
    sales_motion: str = "unknown"     # self-serve | sales-led | hybrid | retail
    price_points: list[str] = field(default_factory=list)
    currency: str = ""
    plan_names: list[str] = field(default_factory=list)
    billing_periods: list[str] = field(default_factory=list)
    has_free_tier: bool | None = None
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class Scale:
    headcount_estimate: str = ""
    headcount_basis: str = ""
    named_people: list[dict[str, str]] = field(default_factory=list)
    leadership: list[dict[str, str]] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    service_areas: list[str] = field(default_factory=list)
    named_customers: list[str] = field(default_factory=list)
    customer_count_claim: str = ""
    founded_year: int | None = None
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class Momentum:
    open_roles: int | None = None
    hiring_departments: list[str] = field(default_factory=list)
    role_titles: list[str] = field(default_factory=list)
    last_content_date: date | None = None
    posts_per_month: float | None = None
    content_window_days: int | None = None
    funding_mentions: list[str] = field(default_factory=list)
    ownership_notes: list[str] = field(default_factory=list)
    copyright_year: int | None = None
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class Operations:
    tech: list[TechFinding] = field(default_factory=list)
    platform_dependencies: list[str] = field(default_factory=list)
    integrations: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class TrustProfile:
    legal_pages: dict[str, str] = field(default_factory=dict)
    compliance_claims: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    addresses: list[str] = field(default_factory=list)
    opening_hours: str = ""
    socials: dict[str, str] = field(default_factory=dict)
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class Score:
    value: float          # 0-100
    band: str             # thin | emerging | established | strong
    rationale: list[str] = field(default_factory=list)
    # Some measures simply do not apply to some businesses — a landscaper has no
    # reason to blog, so a low momentum score would say more about the yardstick
    # than the company. Those are reported as unmeasured rather than as low.
    assessable: bool = True


@dataclass
class ScoreCard:
    maturity: Score
    momentum: Score
    transparency: Score
    evidence_coverage: Score

    def as_pairs(self) -> list[tuple[str, Score]]:
        # "Maturity" invited readers to hear a verdict on the company; a
        # twenty-year-old firm with a sparse site scored "emerging". The
        # measure has always been how much the site documents, so it says so.
        return [
            ("Public footprint", self.maturity),
            ("Momentum", self.momentum),
            ("Transparency", self.transparency),
            ("Evidence coverage", self.evidence_coverage),
        ]


# --- Top-level brief -------------------------------------------------------


@dataclass
class CompanyBrief:
    """The deliverable: what a buyer reads."""

    domain: str
    canonical_url: str = ""
    generated_at: datetime | None = None
    version: str = field(default_factory=lambda: _package_version())

    name: str = ""
    tagline: str = ""
    description: str = ""
    industry_tags: list[str] = field(default_factory=list)

    headline: str = ""
    narrative: str = ""
    narrative_source: str = "deterministic"

    business_model: BusinessModel = field(default_factory=BusinessModel)
    scale: Scale = field(default_factory=Scale)
    momentum: Momentum = field(default_factory=Momentum)
    operations: Operations = field(default_factory=Operations)
    trust: TrustProfile = field(default_factory=TrustProfile)

    # Federal motor-carrier record, when one could be matched confidently.
    # Typed loosely to keep this module free of source-specific imports; it is
    # a ``sources.fmcsa.Carrier`` dataclass and serializes like any other.
    fleet: Any = None
    fleet_note: str = ""
    # Why there is no record: absent, inactive, unreachable, or unmatched.
    # Risk flags dispatch on this rather than on the note's wording.
    fleet_note_kind: str = ""

    scores: ScoreCard | None = None
    signals: list[Signal] = field(default_factory=list)
    risk_flags: list[RiskFlag] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    diligence_questions: list[str] = field(default_factory=list)

    pages: list[dict[str, Any]] = field(default_factory=list)
    fetch_notes: list[str] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        return self.name or self.domain

    def all_evidence(self) -> list[Evidence]:
        seen: set[tuple[str, str, str]] = set()
        out: list[Evidence] = []
        buckets = (
            self.business_model.evidence,
            self.scale.evidence,
            self.momentum.evidence,
            self.operations.evidence,
            self.trust.evidence,
        )
        for bucket in buckets:
            for ev in bucket:
                key = (ev.field, ev.value, ev.source_url)
                if key not in seen:
                    seen.add(key)
                    out.append(ev)
        for sig in self.signals:
            for ev in sig.evidence:
                key = (ev.field, ev.value, ev.source_url)
                if key not in seen:
                    seen.add(key)
                    out.append(ev)
        return out


# --- Serialization ---------------------------------------------------------


def to_jsonable(obj: Any) -> Any:
    """Recursively convert dataclasses/dates into JSON-safe primitives."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: to_jsonable(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    return obj
