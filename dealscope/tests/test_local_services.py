"""Local trade businesses — landscapers, plumbers, HVAC, salons.

These are a large share of the businesses that actually change hands, and the
tool originally had no concept of them: it read a landscaping company as
"developer tools" because "api" appears inside "landscaping".

The fixtures here are deliberately generic — a plumber and a salon, not the
site that exposed the bug — so the tests hold the category rather than one page.
"""

from __future__ import annotations

from datetime import date

import pytest

from dealscope.extract import commerce, contact, identity
from dealscope.extract.identity import count_keyword
from dealscope.models import CompanyBrief
from dealscope.scoring import build_diligence_questions, build_risk_flags, score_momentum

from .conftest import make_page

PLUMBER = """<!doctype html><html><head>
<title>Redgate Plumbing &amp; Heating | Springfield, IL</title>
<meta name="description" content="Family-owned plumbing and heating serving Springfield since 1984.">
</head><body>
<nav><a href="/about">About Us</a><a href="/services">Services</a><a href="/contact">Contact</a></nav>
<h1>Springfield's plumbing and heating specialists since 1984</h1>
<p>Call now: <a href="tel:+12175550142">(217) 555-0142</a></p>
<p>Free estimate on all installations. Licensed and insured. Family-owned.</p>
<p>Proudly serving Springfield, Chatham and Rochester.</p>
<p>Residential &amp; commercial. Emergency service available 24/7.</p>
<p>Schedule an appointment online or request a quote today.</p>
<p>Mon - Fri 7:00 am to 5:00 pm</p>
<p>Water heater installation, drain cleaning, furnace repair and maintenance.</p>
<footer>&copy; 2026 Redgate Plumbing &amp; Heating</footer>
</body></html>"""

SALON = """<!doctype html><html><head><title>Wildflower Hair Studio</title></head><body>
<h1>Wildflower Hair Studio</h1>
<p>Book online or call today. Serving Portland since 2011.</p>
<p>Licensed &amp; insured stylists. Free consultation for colour clients.</p>
<p>Tue - Sat 9:00 am - 6:00 pm</p>
</body></html>"""


@pytest.fixture
def plumber_pages():
    return [make_page("https://redgate.test/", "home", PLUMBER)]


@pytest.fixture
def salon_pages():
    return [make_page("https://wildflower.test/", "home", SALON)]


# --- the substring bug ---


def test_keywords_match_whole_words_only():
    """"api" must not match inside "landscaping"."""
    assert count_keyword("we offer landscaping and hardscaping", "api") == 0
    assert count_keyword("our api is documented", "api") == 1
    assert count_keyword("rapid capital therapies", "api") == 0


def test_a_landscaper_is_not_developer_tools():
    page = make_page(
        "https://green.test/", "home",
        "<html><head><title>Greenway Landscaping</title></head><body>"
        "<h1>Landscaping Services</h1>"
        "<p>Residential landscaping and commercial landscaping. Free estimate. "
        "Licensed and insured. Serving Tampa Bay. Call now.</p></body></html>",
    )
    data, _ = identity.extract([page], "green.test")
    assert "Developer tools" not in data["industry_tags"]


# --- the model ---


@pytest.mark.parametrize("fixture", ["plumber_pages", "salon_pages"])
def test_local_trades_are_recognised(fixture, request):
    pages = request.getfixturevalue(fixture)
    model, _ = commerce.extract(pages)
    assert model.primary == "local_services"
    assert model.signal_count >= 3


def test_a_consultancy_is_still_read_as_services():
    """The new model must not swallow B2B consultancies."""
    page = make_page(
        "https://advisory.test/", "home",
        "<body><h1>Strategy consulting</h1>"
        "<p>Our clients include global banks. Book a consultation. "
        "Our approach is bespoke and tailored to your engagement. "
        "Case studies show our process. Request a proposal. Retainer available.</p></body>",
    )
    model, _ = commerce.extract([page])
    assert model.primary == "services"


AMBIGUOUS_TRADE_HTML = (
    "<body><h1>Harding & Sons</h1>"
    "<p>We install, repair and maintain. Our team will take care of it. "
    "Residential and commercial. Family-owned since 1994. "
    "Schedule a visit and we will give you a free estimate.</p></body>"
)


def test_contact_facts_settle_the_services_local_services_tie():
    """Vocabulary alone could not tell a trade business from a consultancy.

    "We serve our clients" and "we serve Dayton" read the same to a keyword
    table. A phone in the masthead, opening hours, a named service area and a
    street address do not — they are structural, and much harder to fake.
    """
    page = make_page("https://harding.test/", "home", AMBIGUOUS_TRADE_HTML)

    with_facts, _ = commerce.extract(
        [page],
        contact_facts={
            "service_areas": ["Dayton, Springfield"],
            "phone_in_header": True,
            "opening_hours": "Mon-Fri 8am-5pm",
            "addresses": ["114 Mill Road, Dayton, OH 45402"],
        },
    )
    assert with_facts.primary == "local_services"
    assert "a published service area" in " ".join(
        e.snippet for e in with_facts.evidence if e.field == "business_model.primary"
    )


def test_contact_facts_do_not_drag_a_consultancy_into_local_services():
    """The mirror: an office with a phone and an address is not a trade business."""
    page = make_page(
        "https://advisory.test/", "home",
        "<body><h1>Strategy consulting</h1>"
        "<p>Our clients include global banks. Book a consultation. "
        "Our approach is bespoke and tailored to your engagement. "
        "Case studies show our process. Request a proposal. Retainer available.</p></body>",
    )
    model, _ = commerce.extract(
        [page],
        contact_facts={
            "phone_in_header": True,
            "addresses": ["30 Finsbury Square, London"],
        },
    )
    assert model.primary == "services"


def test_a_phone_in_the_footer_is_not_a_phone_in_the_header():
    """The signal is the masthead specifically, not "publishes a number"."""
    from dealscope.extract import contact as contact_module

    header = make_page(
        "https://a.test/contact", "contact",
        "<body><header><a href='tel:+15135550101'>(513) 555-0101</a></header>"
        "<p>Call us.</p></body>",
    )
    footer = make_page(
        "https://b.test/contact", "contact",
        "<body><p>Call us.</p>"
        "<footer><a href='tel:+15135550101'>(513) 555-0101</a></footer></body>",
    )
    assert contact_module.extract([header], "a.test")[0]["phone_in_header"] is True
    assert contact_module.extract([footer], "b.test")[0]["phone_in_header"] is False


# --- local signals ---


def test_service_area_and_hours_are_extracted(plumber_pages):
    data, _ = contact.extract(plumber_pages, "redgate.test")
    assert any("Springfield" in area for area in data["service_areas"])
    assert data["opening_hours"]
    assert "Licensed & insured" in data["compliance_claims"]


def test_phone_is_found_for_a_business_built_around_calls(plumber_pages):
    data, _ = contact.extract(plumber_pages, "redgate.test")
    assert data["phones"]


# --- scoring ---


def test_momentum_is_reported_as_unmeasured_not_low(plumber_pages):
    """A plumber has no blog. That is not evidence of decline."""
    brief = CompanyBrief(domain="redgate.test")
    brief.business_model, _ = commerce.extract(plumber_pages)
    brief.momentum.copyright_year = date.today().year

    score = score_momentum(brief, date.today())
    assert score.assessable is False
    assert score.band == "not assessable"
    assert any("no reason to blog" in reason for reason in score.rationale)


def test_a_saas_business_still_gets_a_real_momentum_score(saas_pages):
    brief = CompanyBrief(domain="kettlewind.test")
    brief.business_model, _ = commerce.extract(saas_pages)
    brief.momentum.open_roles = 3
    brief.momentum.last_content_date = date.today()

    score = score_momentum(brief, date.today())
    assert score.assessable is True
    assert score.value > 0


def test_absent_pricing_is_not_a_flag_for_a_trade_business(plumber_pages):
    """Every job is quoted, so no public price list is normal."""
    brief = CompanyBrief(domain="redgate.test", pages=[{"role": "home", "words": 500, "url": "u"}])
    brief.business_model, _ = commerce.extract(plumber_pages)
    flags = build_risk_flags(brief, date.today())
    assert not any(f.key == "no_public_pricing" for f in flags)


def test_absent_pricing_is_still_a_flag_for_saas():
    brief = CompanyBrief(domain="app.test", pages=[{"role": "home", "words": 500, "url": "u"}])
    brief.business_model.primary = "saas"
    flags = build_risk_flags(brief, date.today())
    assert any(f.key == "no_public_pricing" for f in flags)


def test_licence_claims_prompt_for_certificates(plumber_pages):
    brief = CompanyBrief(domain="redgate.test", pages=[{"role": "home", "words": 500, "url": "u"}])
    brief.business_model, _ = commerce.extract(plumber_pages)
    brief.trust.compliance_claims = ["Licensed & insured"]

    flags = build_risk_flags(brief, date.today())
    credential = next(f for f in flags if f.key == "unverified_credentials")
    assert "certificates of insurance" in credential.detail


def test_questions_suit_a_trade_business(plumber_pages):
    brief = CompanyBrief(domain="redgate.test")
    brief.business_model, _ = commerce.extract(plumber_pages)
    joined = " ".join(build_diligence_questions(brief)).lower()

    assert "seasonal" in joined
    assert "crews" in joined or "technicians" in joined
    assert "vehicles" in joined
    assert "mrr" not in joined          # SaaS questions must not leak in
    assert "average order value" not in joined
