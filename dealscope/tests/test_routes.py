"""Route-business paths: carrier lookup by number, and listing-URL refusal.

These cover the FedEx ISP / motor-carrier case, where the business often has
no website and the seller supplies a USDOT number instead.
"""

from __future__ import annotations

import pytest

from dealscope.fetch import is_listing_venue, normalize_domain
from dealscope.sources import fmcsa


# --- listing URLs must not be read as the marketplace ---


def test_a_listing_url_is_refused_rather_than_analysed():
    """Only the host survived normalisation, so this returned a brief on
    BizBuySell — confident, well-formatted, and about the wrong company."""
    with pytest.raises(ValueError) as caught:
        normalize_domain(
            "https://www.bizbuysell.com/business-opportunity/"
            "fedex-ground-routes-columbus-oh/2312345/"
        )
    message = str(caught.value)
    assert "listing" in message
    assert "--usdot" in message


def test_the_marketplace_itself_is_still_analysable():
    """The mirror: refusing listings must not refuse the company that runs them."""
    assert normalize_domain("https://www.bizbuysell.com/") == "www.bizbuysell.com"
    assert normalize_domain("bizbuysell.com") == "bizbuysell.com"


def test_an_ordinary_company_url_with_a_path_still_works():
    """The other mirror: a path is only suspicious on a listing venue."""
    assert normalize_domain("https://acme-trucking.com/about/team") == "acme-trucking.com"


def test_listing_venue_matches_subdomains_but_not_lookalikes():
    assert is_listing_venue("www.bizquest.com")
    assert is_listing_venue("bizquest.com")
    assert not is_listing_venue("bizquestion.com")
    assert not is_listing_venue("acme.com")


# --- carrier lookup by number ---


class _FakePage:
    def __init__(self, html: str, ok: bool = True, status: int = 200, error=None):
        self.html, self.ok, self.status, self.error = html, ok, status, error


class _FakeFetcher:
    def __init__(self, page):
        self._page = page
        self.urls: list[str] = []

    def get(self, url, **_kwargs):
        self.urls.append(url)
        return self._page


SNAPSHOT_HTML = """
<html><body><table>
<tr><th>USDOT Number:</th><td>1554728</td></tr>
<tr><th>Legal Name:</th><td>BUCKEYE PARCEL LLC</td></tr>
<tr><th>USDOT Status:</th><td>ACTIVE</td></tr>
<tr><th>Power Units:</th><td>12</td></tr>
<tr><th>Drivers:</th><td>15</td></tr>
<tr><th>Physical Address:</th><td>114 MILL RD, COLUMBUS, OH 43004</td></tr>
<tr><th>MCS-150 Form Date:</th><td>03/27/2026</td></tr>
</table></body></html>
"""


def test_a_usdot_number_needs_no_name_matching():
    """A number is an identity — nothing to match, nothing to get wrong.

    This is the path that works for route businesses, which frequently have
    no website for a name to be scraped from in the first place.
    """
    fetcher = _FakeFetcher(_FakePage(SNAPSHOT_HTML))
    carrier, note, _kind = fmcsa.get_snapshot_with_note(fetcher, "1554728")
    assert note == ""
    assert carrier is not None
    assert carrier.power_units == 12
    assert carrier.drivers == 15
    assert carrier.is_active
    assert "1554728" in fetcher.urls[0]


def test_an_inactive_record_is_reported_as_a_finding():
    """Authority that once existed and is now dead is something to ask about."""
    fetcher = _FakeFetcher(
        _FakePage("<html><head><title>SAFER Web - Company Snapshot RECORD INACTIVE"
                  "</title></head><body></body></html>")
    )
    carrier, note, _kind = fmcsa.get_snapshot_with_note(fetcher, "202964")
    assert carrier is None
    assert "inactive" in note.lower()
    assert "authority" in note.lower()


def test_a_missing_record_is_reported_as_not_a_finding():
    """The mirror, and the one that matters most.

    Vehicles under 10,001 lbs GVWR need no USDOT number, so a van-only P&D
    fleet legitimately has no SAFER record. Rendering that as a red flag would
    manufacture a finding out of an absence.
    """
    fetcher = _FakeFetcher(_FakePage("<html><body>nothing here</body></html>"))
    carrier, note, _kind = fmcsa.get_snapshot_with_note(fetcher, "9999999")
    assert carrier is None
    assert "not" in note.lower() and "finding" in note.lower()
    assert "10,001" in note


def test_an_unreachable_register_is_not_reported_as_an_absent_record():
    fetcher = _FakeFetcher(_FakePage("", ok=False, status=503, error="timeout"))
    carrier, note, _kind = fmcsa.get_snapshot_with_note(fetcher, "1554728")
    assert carrier is None
    assert "could not be reached" in note


# --- the note's kind, not its wording, decides the flag ---


def test_a_direct_lookup_carries_its_own_evidence():
    """Only find_carrier attached evidence, so the --usdot path cited nothing.

    The brief showed power units and drivers with no source behind them, and
    the fleet risk flags rendered with an empty evidence list.
    """
    fetcher = _FakeFetcher(_FakePage(SNAPSHOT_HTML))
    carrier, _note, _kind = fmcsa.get_snapshot_with_note(fetcher, "1554728")
    fields = {e.field for e in carrier.evidence}
    assert "fleet.power_units" in fields
    assert all(e.source_url for e in carrier.evidence)


def test_an_absent_record_raises_no_risk_flag():
    """The whole point of the note is that absence is not a finding.

    The flag suppression matched one phrase from find_carrier, so all three
    new notes raised "could not confidently match" — turning the sentence that
    says this is not a finding into a finding.
    """
    from datetime import date

    from dealscope.models import CompanyBrief
    from dealscope.scoring import build_risk_flags

    brief = CompanyBrief(domain="x.test", pages=[{"role": "home", "words": 900, "url": "u"}])
    brief.fleet_note = "no FMCSA record was returned for USDOT 9999999. Absence is not…"
    brief.fleet_note_kind = fmcsa.NOTE_ABSENT

    keys = {f.key for f in build_risk_flags(brief, date.today())}
    assert "carrier_unmatched" not in keys
    assert "carrier_inactive_record" not in keys


def test_an_unreachable_register_raises_no_risk_flag():
    from datetime import date

    from dealscope.models import CompanyBrief
    from dealscope.scoring import build_risk_flags

    brief = CompanyBrief(domain="x.test", pages=[{"role": "home", "words": 900, "url": "u"}])
    brief.fleet_note = "the FMCSA register could not be reached for USDOT 1554728 (timeout)"
    brief.fleet_note_kind = fmcsa.NOTE_UNREACHABLE

    assert not {f.key for f in build_risk_flags(brief, date.today())} & {
        "carrier_unmatched", "carrier_inactive_record"
    }


def test_an_inactive_record_is_a_high_flag_not_a_match_failure():
    """The mirror: a dead authority must not be downgraded to "unmatched"."""
    from datetime import date

    from dealscope.models import CompanyBrief
    from dealscope.scoring import build_risk_flags

    brief = CompanyBrief(domain="x.test", pages=[{"role": "home", "words": 900, "url": "u"}])
    brief.fleet_note = "USDOT 202964 exists but SAFER reports the record as inactive…"
    brief.fleet_note_kind = fmcsa.NOTE_INACTIVE

    flags = {f.key: f for f in build_risk_flags(brief, date.today())}
    assert "carrier_inactive_record" in flags
    assert flags["carrier_inactive_record"].severity == "high"
    assert "carrier_unmatched" not in flags


def test_listing_urls_are_refused_by_query_and_fragment_too():
    """Venues address listings differently; only the path was being checked."""
    for url in (
        "https://www.bizbuysell.com/?listing=2312345",
        "https://www.bizbuysell.com/#/listing/2312345",
        "https://www.bizquest.com/business-for-sale/routes/98765/",
    ):
        with pytest.raises(ValueError):
            normalize_domain(url)
    # And the mirror, unchanged: the bare venue is still analysable.
    assert normalize_domain("https://www.bizbuysell.com") == "www.bizbuysell.com"


def test_one_usdot_cannot_be_spread_across_a_batch():
    """A number identifies one carrier; a batch would share one fleet."""
    from dealscope.cli import _build_parser, _run_analyze

    args = _build_parser().parse_args(
        ["analyze", "a.test", "b.test", "--usdot", "1554728"]
    )
    with pytest.raises(SystemExit):
        _run_analyze(args)


def test_a_supplied_number_says_the_link_is_unverified():
    """--usdot attaches a record to whatever domain was passed.

    The number is asserted by the user, not established by the tool, so the
    brief has to say so — otherwise it prints a stranger's fleet and crash
    history beside any website it is handed, with no hint that the pairing
    was never checked.
    """
    fetcher = _FakeFetcher(_FakePage(SNAPSHOT_HTML))
    carrier, _note, _kind = fmcsa.get_snapshot_with_note(fetcher, "1554728")
    assert "no check that this carrier is the business" in carrier.how_found


def test_a_name_matched_record_still_reports_its_score():
    """The mirror: the matching path has a score, and still shows it."""
    from dealscope.sources.fmcsa import Carrier

    matched = Carrier(usdot="1", legal_name="ACME HAULING")
    matched.match_score = 0.91
    matched.match_basis = "name similarity 0.94; state matches"
    matched.considered = 4
    assert "91%" in matched.how_found
    assert "4 candidate(s) considered" in matched.how_found


# --- annual mileage: the closest public measure of operating scale ---


MILEAGE_HTML = SNAPSHOT_HTML.replace(
    "<tr><th>MCS-150 Form Date:</th><td>03/27/2026</td></tr>",
    "<tr><th>MCS-150 Form Date:</th><td>03/27/2026</td></tr>"
    "<tr><th>MCS-150 Mileage (Year):</th><td>17,581,156 (2025)</td></tr>",
)


def test_annual_miles_and_utilisation_are_read():
    """Power units say how many trucks exist; miles say how hard they ran."""
    fetcher = _FakeFetcher(_FakePage(MILEAGE_HTML))
    carrier, _note, _kind = fmcsa.get_snapshot_with_note(fetcher, "54988")
    assert carrier.annual_miles == 17_581_156
    assert carrier.mileage_year == "2025"
    # 17,581,156 over 12 power units in the fixture.
    assert carrier.miles_per_unit == round(17_581_156 / 12)


def test_mileage_is_absent_rather_than_zero_when_unfiled():
    """A carrier that never filed mileage must not read as having driven none."""
    fetcher = _FakeFetcher(_FakePage(SNAPSHOT_HTML))
    carrier, _note, _kind = fmcsa.get_snapshot_with_note(fetcher, "1554728")
    assert carrier.annual_miles is None
    assert carrier.miles_per_unit is None
    assert carrier.mileage_year == ""


def test_utilisation_needs_both_numbers():
    """No trucks on file means no division — not a divide-by-zero, not a guess."""
    from dealscope.sources.fmcsa import Carrier

    c = Carrier(usdot="1", mcs150_mileage="100,000 (2025)")
    c.power_units = None
    assert c.annual_miles == 100_000
    assert c.miles_per_unit is None
