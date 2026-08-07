"""FMCSA carrier lookup, offline against recorded SAFER pages.

The parsing tests matter, but the matching tests matter more: attaching the
wrong carrier's fleet size and crash history to a business would be worse than
returning nothing at all.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from dealscope.models import CompanyBrief, Page
from dealscope.scoring import build_risk_flags
from dealscope.sources import fmcsa

FIXTURES = Path(__file__).parent / "fixtures"
SNAPSHOT = (FIXTURES / "safer_snapshot.html").read_text(encoding="utf-8")
SEARCH = (FIXTURES / "safer_search.html").read_text(encoding="utf-8")


class FakeFetcher:
    """Serves recorded SAFER pages; records what was requested."""

    def __init__(self, snapshots: dict[str, str] | None = None, search: str = SEARCH):
        self.snapshots = snapshots or {}
        self.search = search
        self.requested: list[str] = []

    def post(self, url, data, role="other"):
        self.requested.append(f"POST {data.get('query_string')}")
        return Page(url=url, final_url=url, status=200, html=self.search, role=role)

    def get(self, url, role="other", force_render=False):
        self.requested.append(url)
        usdot = url.rsplit("=", 1)[-1]
        html = self.snapshots.get(usdot)
        if html is None:
            return Page(url=url, status=404, error="HTTP 404", role=role)
        return Page(url=url, final_url=url, status=200, html=html, role=role)


# --- parsing ---


def test_snapshot_parses_every_field_we_rely_on():
    carrier = fmcsa.parse_snapshot(SNAPSHOT)

    assert carrier.usdot == "1597181"
    assert carrier.legal_name == "DOT INC"
    assert carrier.entity_type == "CARRIER"
    assert carrier.operating_status == "ACTIVE"      # SAFER calls it "USDOT Status"
    assert carrier.power_units == 1
    assert carrier.drivers == 1
    assert carrier.state == "AZ"
    assert carrier.phone == "(602) 276-3357"
    assert carrier.mcs150_date == date(2007, 1, 18)
    assert carrier.source_url.endswith("1597181")


def test_literal_none_is_not_treated_as_a_date():
    """SAFER writes the word "None" into empty date fields."""
    carrier = fmcsa.parse_snapshot(SNAPSHOT)
    assert carrier.out_of_service_date == ""
    assert carrier.is_active is True


def test_unparseable_page_returns_nothing_rather_than_a_blank_carrier():
    assert fmcsa.parse_snapshot("<html><body>nope</body></html>") is None


def test_search_results_yield_candidate_usdot_numbers():
    found = fmcsa.parse_search_results(SEARCH)
    assert len(found) >= 5
    assert all(number.isdigit() for number in found)


# --- name normalisation ---


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Retty Logistics LLC", "retty logistics"),
        ("RETTY LOGISTICS, L.L.C.", "retty logistics"),
        ("The Onorato Company Inc.", "onorato"),
    ],
)
def test_legal_form_words_are_stripped(raw, expected):
    assert fmcsa.normalize_name(raw) == expected


def test_similarity_ignores_legal_form_differences():
    assert fmcsa.name_similarity("Retty Logistics LLC", "RETTY LOGISTICS INC") > 0.95
    assert fmcsa.name_similarity("Retty Logistics", "Sunrise Plumbing") < 0.5


# --- matching discipline ---


def _snapshot_with(**overrides) -> str:
    """Rewrite the recorded snapshot's name so we can test matching."""
    html = SNAPSHOT
    if "legal_name" in overrides:
        html = html.replace(">DOT INC", ">" + overrides["legal_name"])
    if "state" in overrides:
        html = html.replace("PHOENIX, AZ &nbsp; 85041", f"SOMEWHERE, {overrides['state']} &nbsp; 12345")
        html = html.replace("PHOENIX, AZ", f"SOMEWHERE, {overrides['state']}")
    return html


def test_a_good_match_is_accepted_and_cited():
    fetcher = FakeFetcher({"1597181": _snapshot_with(legal_name="RETTY LOGISTICS LLC")})
    fetcher.search = 'href="query.asp?query_string=1597181"'

    carrier, why_not = fmcsa.find_carrier(fetcher, "Retty Logistics")

    assert carrier is not None, why_not
    assert carrier.usdot == "1597181"
    assert carrier.match_score >= 0.7
    assert carrier.evidence
    assert all(e.source_url.endswith("1597181") for e in carrier.evidence)
    assert all(e.method == "fmcsa" for e in carrier.evidence)


def test_a_weak_name_match_is_refused():
    fetcher = FakeFetcher({"1597181": SNAPSHOT})
    fetcher.search = 'href="query.asp?query_string=1597181"'

    carrier, why_not = fmcsa.find_carrier(fetcher, "Sunrise Plumbing and Heating")

    assert carrier is None
    assert "too weak a match" in why_not
    assert "DOT INC" in why_not          # says what it saw, rather than going quiet


def test_a_wrong_state_defeats_a_similar_name():
    fetcher = FakeFetcher({"1597181": _snapshot_with(legal_name="RETTY LOGISTICS LLC")})
    fetcher.search = 'href="query.asp?query_string=1597181"'

    carrier, why_not = fmcsa.find_carrier(fetcher, "Retty Logistics", state="FL")

    assert carrier is None
    assert "state differs" in why_not


def test_two_equally_good_candidates_are_reported_as_ambiguous():
    fetcher = FakeFetcher(
        {
            "1111111": _snapshot_with(legal_name="RETTY LOGISTICS LLC"),
            "2222222": _snapshot_with(legal_name="RETTY LOGISTICS LLC"),
        }
    )
    fetcher.search = ('href="query.asp?query_string=1111111" '
                      'href="query.asp?query_string=2222222"')

    carrier, why_not = fmcsa.find_carrier(fetcher, "Retty Logistics")

    assert carrier is None
    assert "about equally well" in why_not


def test_no_search_results_is_reported_plainly():
    fetcher = FakeFetcher({})
    fetcher.search = "<html>no matches</html>"

    carrier, why_not = fmcsa.find_carrier(fetcher, "Nonexistent Hauling")
    assert carrier is None
    assert "no FMCSA record found" in why_not


def test_an_empty_name_never_searches():
    fetcher = FakeFetcher({})
    carrier, why_not = fmcsa.find_carrier(fetcher, "   ")
    assert carrier is None
    assert fetcher.requested == []


# --- how the record reaches the brief ---


def test_an_inactive_carrier_is_a_high_severity_flag():
    carrier = fmcsa.parse_snapshot(SNAPSHOT)
    carrier.operating_status = "INACTIVE"
    carrier.out_of_service_date = "01/05/2024"
    carrier.evidence = fmcsa.build_evidence(carrier)

    brief = CompanyBrief(domain="x.test", pages=[{"role": "home", "words": 900, "url": "u"}])
    brief.fleet = carrier
    flags = build_risk_flags(brief, date.today())

    flag = next(f for f in flags if f.key == "carrier_inactive")
    assert flag.severity == "high"


def test_a_stale_mcs150_is_flagged():
    carrier = fmcsa.parse_snapshot(SNAPSHOT)      # filed 2007
    carrier.evidence = fmcsa.build_evidence(carrier)

    brief = CompanyBrief(domain="x.test", pages=[{"role": "home", "words": 900, "url": "u"}])
    brief.fleet = carrier
    flags = build_risk_flags(brief, date.today())

    assert any(f.key == "stale_mcs150" for f in flags)


def test_an_ambiguous_match_becomes_a_low_flag_not_a_silent_gap():
    brief = CompanyBrief(domain="x.test", pages=[{"role": "home", "words": 900, "url": "u"}])
    brief.fleet = None
    brief.fleet_note = "several FMCSA records match “Acme Hauling” about equally well"

    flags = build_risk_flags(brief, date.today())
    assert any(f.key == "carrier_unmatched" for f in flags)


def test_a_plain_absence_of_record_is_not_a_flag():
    brief = CompanyBrief(domain="x.test", pages=[{"role": "home", "words": 900, "url": "u"}])
    brief.fleet_note = "no FMCSA record found matching “Bramble & Oak”"

    flags = build_risk_flags(brief, date.today())
    assert not any(f.key == "carrier_unmatched" for f in flags)


def test_fleet_size_lifts_the_maturity_score():
    from dealscope.scoring import score_maturity

    plain = CompanyBrief(domain="x.test")
    withfleet = CompanyBrief(domain="x.test")
    carrier = fmcsa.parse_snapshot(SNAPSHOT)
    carrier.power_units = 60
    withfleet.fleet = carrier

    assert score_maturity(withfleet, date.today()).value > score_maturity(plain, date.today()).value


# --- regressions found in code review ---


@pytest.mark.parametrize(
    "company,carrier_name",
    [
        ("Ace Movers", "Palace Movers LLC"),        # substring of a longer word
        ("Ace", "Space Logistics"),
        ("Art", "Stuart Trucking"),
    ],
)
def test_a_name_that_is_merely_a_substring_is_not_a_match(company, carrier_name):
    """"Ace Movers" is not "Palace Movers" — containment must be token-wise."""
    assert fmcsa.name_similarity(company, carrier_name) < fmcsa.MIN_NAME_SIMILARITY


def test_token_containment_still_counts_as_similar():
    """A genuine shortening must still match: whole words, not characters."""
    assert fmcsa.name_similarity("Retty Logistics", "Retty Logistics Services") > 0.8


def test_a_substring_carrier_is_refused_end_to_end():
    fetcher = FakeFetcher({"1597181": _snapshot_with(legal_name="PALACE MOVERS LLC")})
    fetcher.search = 'href="query.asp?query_string=1597181"'

    carrier, why_not = fmcsa.find_carrier(fetcher, "Ace Movers", state="AZ")
    assert carrier is None, f"accepted a wrong carrier: {carrier}"
    assert why_not


@pytest.mark.parametrize(
    "status,active",
    [("ACTIVE", True), ("INACTIVE", False), ("inactive", False), ("", False)],
)
def test_inactive_is_not_read_as_active(status, active):
    """"ACTIVE" in "INACTIVE" is True — the compare has to be exact."""
    assert fmcsa.Carrier(operating_status=status).is_active is active


def test_the_inactive_flag_fires_for_the_literal_status():
    carrier = fmcsa.parse_snapshot(SNAPSHOT)
    carrier.operating_status = "INACTIVE"      # exactly what SAFER writes
    carrier.evidence = fmcsa.build_evidence(carrier)

    brief = CompanyBrief(domain="x.test", pages=[{"role": "home", "words": 900, "url": "u"}])
    brief.fleet = carrier
    flags = build_risk_flags(brief, date.today())

    assert any(f.key == "carrier_inactive" and f.severity == "high" for f in flags)


def _brief_with_fleet() -> CompanyBrief:
    carrier = fmcsa.parse_snapshot(SNAPSHOT)
    carrier.power_units = 42
    carrier.drivers = 39
    carrier.match_score = 0.91
    carrier.match_basis = "name similarity 0.95; state matches (AZ)"
    carrier.considered = 3
    carrier.evidence = fmcsa.build_evidence(carrier)
    brief = CompanyBrief(domain="hauler.test", name="Hauler", headline="h", narrative="n")
    brief.fleet = carrier
    return brief


def test_every_renderer_shows_the_fleet_record():
    """The HTML brief used to drop this section entirely — silently."""
    from dealscope.render import to_html, to_markdown, to_text

    brief = _brief_with_fleet()
    for name, output in (
        ("markdown", to_markdown(brief)),
        ("html", to_html(brief)),
        ("text", to_text(brief)),
    ):
        assert "1597181" in output, f"{name} lost the USDOT number"
        assert "42" in output, f"{name} lost the power-unit count"


def test_every_renderer_explains_a_refused_match():
    """A refused match must not look identical to no lookup at all."""
    from dealscope.render import to_html, to_markdown, to_text

    brief = CompanyBrief(domain="x.test", name="X", headline="h", narrative="n")
    brief.fleet_note = "several FMCSA records match about equally well"

    for name, output in (
        ("markdown", to_markdown(brief)),
        ("html", to_html(brief)),
        ("text", to_text(brief)),
    ):
        assert "equally well" in output, f"{name} hid the reason no record was attached"
