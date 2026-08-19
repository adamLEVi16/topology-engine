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
    carrier, note = fmcsa.get_snapshot_with_note(fetcher, "1554728")
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
    carrier, note = fmcsa.get_snapshot_with_note(fetcher, "202964")
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
    carrier, note = fmcsa.get_snapshot_with_note(fetcher, "9999999")
    assert carrier is None
    assert "not" in note.lower() and "finding" in note.lower()
    assert "10,001" in note


def test_an_unreachable_register_is_not_reported_as_an_absent_record():
    fetcher = _FakeFetcher(_FakePage("", ok=False, status=503, error="timeout"))
    carrier, note = fmcsa.get_snapshot_with_note(fetcher, "1554728")
    assert carrier is None
    assert "could not be reached" in note
