"""Scoring, narration, rendering, and the end-to-end pipeline (offline)."""

from __future__ import annotations

import json
from datetime import date

import pytest

from dealscope import analyzer
from dealscope.config import Config
from dealscope.models import CompanyBrief, Page, to_jsonable
from dealscope.render import to_html, to_markdown, to_text
from dealscope.scoring import build_diligence_questions, build_risk_flags, build_unknowns

from .conftest import make_page


class FakeFetcher:
    """Serves fixture HTML instead of touching the network."""

    def __init__(self, site: dict[str, str], config: Config | None = None):
        self.site = site
        self.config = config or Config()
        self.notes: list[str] = []
        self.robots_blocked: list[str] = []
        self.fetch_count = 0
        self.renderer = None

    def resolve_home(self, domain: str) -> Page:
        return self.get(f"https://{domain}/", role="home")

    def delay_for(self, url: str) -> float:
        return 0.0

    def get(self, url: str, role: str = "other", force_render: bool = False) -> Page:
        self.fetch_count += 1
        html = self.site.get(url) or self.site.get(url.rstrip("/"))
        if html is None:
            return Page(url=url, role=role, status=404, error="HTTP 404")
        return make_page(url, role, html)

    def get_text(self, url: str) -> str:
        return ""

    def sitemap_urls(self, url: str) -> list[str]:
        return []

    def allowed(self, url: str) -> bool:
        return True

    def close(self) -> None:
        pass


@pytest.fixture
def brief(saas_site, monkeypatch) -> CompanyBrief:
    monkeypatch.setattr(
        analyzer, "Fetcher", lambda config: FakeFetcher(saas_site, config)
    )
    return analyzer.analyze("kettlewind.test", Config(delay=0, use_cache=False))


# --- pipeline ---


def test_pipeline_builds_a_complete_brief(brief):
    assert brief.name == "Kettlewind"
    assert brief.domain == "kettlewind.test"
    assert brief.business_model.primary == "saas"
    assert brief.scale.founded_year == 2016
    assert brief.scale.headcount_estimate == "~18"
    assert brief.momentum.open_roles == 3
    assert len(brief.trust.legal_pages) == 2
    assert brief.narrative and brief.headline
    assert brief.narrative_source == "deterministic"


def test_pipeline_records_evidence_with_sources(brief):
    evidence = brief.all_evidence()
    assert len(evidence) > 15
    assert all(e.source_url.startswith("https://kettlewind.test") for e in evidence)
    assert all(0.0 <= e.confidence <= 1.0 for e in evidence)


def test_pipeline_scores_a_well_documented_site_highly(brief):
    assert brief.scores is not None
    assert brief.scores.maturity.value >= 60
    assert brief.scores.transparency.value >= 70
    assert brief.scores.evidence_coverage.value >= 75
    # Scores always carry their reasoning.
    assert all(score.rationale for _label, score in brief.scores.as_pairs())


def test_pipeline_asks_model_specific_questions(brief):
    joined = " ".join(brief.diligence_questions).lower()
    assert "mrr" in joined or "arr" in joined          # SaaS-specific
    assert "tax returns" in joined                      # universal
    assert "average order value" not in joined          # e-commerce, not applicable


def test_unreachable_site_returns_an_honest_brief(monkeypatch):
    monkeypatch.setattr(analyzer, "Fetcher", lambda config: FakeFetcher({}, config))
    result = analyzer.analyze("nothing-here.test", Config(delay=0, use_cache=False))

    assert result.scores.evidence_coverage.value == 0
    assert any(flag.key == "unreachable" for flag in result.risk_flags)
    assert result.unknowns and result.diligence_questions
    assert "could be produced" in result.narrative or "unreachable" in result.headline


def test_analyze_rejects_an_unparseable_domain():
    with pytest.raises(ValueError):
        analyzer.analyze("   ")


# --- scoring behaviour ---


def test_missing_evidence_is_reported_as_unknown_not_as_a_negative():
    empty = CompanyBrief(domain="quiet.test")
    unknowns = build_unknowns(empty)
    assert any("Pricing" in u for u in unknowns)
    assert any("owns and runs" in u for u in unknowns)
    # Structural unknowns apply to every company, however well documented.
    assert any("Revenue, margins" in u for u in unknowns)


def test_risk_flags_are_sorted_by_severity():
    empty = CompanyBrief(domain="quiet.test", pages=[{"role": "home", "words": 10, "url": "u"}])
    flags = build_risk_flags(empty, date(2026, 6, 1))
    severities = [f.severity for f in flags]
    assert severities == sorted(severities, key=lambda s: {"high": 0, "medium": 1, "low": 2}[s])
    assert any(f.key == "thin_site" for f in flags)


def test_absence_flags_are_qualified_when_the_site_is_client_rendered():
    empty = CompanyBrief(domain="spa.test", pages=[{"role": "home", "words": 900, "url": "u"}])
    plain = build_risk_flags(empty, date(2026, 6, 1))
    hedged = build_risk_flags(empty, date(2026, 6, 1), client_rendered=True)

    plain_detail = next(f.detail for f in plain if f.key == "no_contact")
    hedged_detail = next(f.detail for f in hedged if f.key == "no_contact")
    assert "client-side" not in plain_detail
    assert "client-side" in hedged_detail


def test_robots_exclusions_are_disclosed_in_flags():
    empty = CompanyBrief(domain="blocked.test", pages=[{"role": "home", "words": 900, "url": "u"}])
    flags = build_risk_flags(empty, date(2026, 6, 1), robots_blocked=4)
    detail = next(f.detail for f in flags if f.key == "no_legal_pages")
    assert "robots.txt" in detail


def test_questions_adapt_to_an_ecommerce_model(shop_pages):
    from dealscope.extract import commerce

    ecom = CompanyBrief(domain="shop.test")
    ecom.business_model, _ = commerce.extract(shop_pages, platform_hints=["Shopify"])
    joined = " ".join(build_diligence_questions(ecom)).lower()
    assert "average order value" in joined
    assert "mrr" not in joined


# --- rendering ---


def test_text_render_contains_the_essentials(brief):
    out = to_text(brief)
    assert brief.headline in out
    assert "QUESTIONS TO ASK THE SELLER" in out
    assert "CANNOT BE DETERMINED" in out
    assert "not a substitute for financial, legal" in out


def test_markdown_render_is_well_formed(brief):
    out = to_markdown(brief)
    assert out.startswith("# ")
    for heading in ("## Summary", "## Scorecard", "## Business model", "## Evidence"):
        assert heading in out
    assert "kettlewind.test" in out


def test_html_render_is_a_complete_escaped_document(brief):
    out = to_html(brief)
    assert out.strip().startswith("<!doctype html>")
    assert "{{" not in out and "{%" not in out
    assert "<title>Kettlewind — buyer brief</title>" in out


def test_html_render_escapes_hostile_content():
    hostile = CompanyBrief(
        domain="evil.test",
        name="<script>alert('xss')</script>",
        narrative="hello",
        headline="x",
    )
    out = to_html(hostile)
    assert "<script>alert" not in out
    assert "&lt;script&gt;" in out


def test_json_render_round_trips(brief):
    payload = json.dumps(to_jsonable(brief))
    restored = json.loads(payload)
    assert restored["name"] == "Kettlewind"
    assert restored["scores"]["maturity"]["value"] > 0
    assert isinstance(restored["diligence_questions"], list)
