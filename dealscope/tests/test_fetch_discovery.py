"""URL handling, HTML-to-text, and page discovery."""

from __future__ import annotations

import pytest

from dealscope.discovery import classify, links_from
from dealscope.fetch import clean_url, html_to_text, normalize_domain, same_site


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("acme.com", "acme.com"),
        ("Acme.COM", "acme.com"),
        ("https://acme.com/pricing?x=1", "acme.com"),
        ("http://www.acme.com", "www.acme.com"),
        ("  acme.co.uk/ ", "acme.co.uk"),
    ],
)
def test_normalize_domain(raw, expected):
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize("bad", ["", "   ", "://"])
def test_normalize_domain_rejects_junk(bad):
    with pytest.raises(ValueError):
        normalize_domain(bad)


def test_clean_url_strips_tracking_and_fragments():
    got = clean_url("https://acme.com/p?utm_source=x&id=7&fbclid=abc#top")
    assert got == "https://acme.com/p?id=7"


def test_clean_url_resolves_relative_against_base():
    assert clean_url("/about", "https://acme.com/x/y") == "https://acme.com/about"


def test_clean_url_rejects_non_http_schemes():
    assert clean_url("mailto:a@b.com") == ""
    assert clean_url("javascript:alert(1)") == ""


def test_same_site_accepts_subdomains_and_www():
    assert same_site("https://blog.acme.com/x", "acme.com")
    assert same_site("https://www.acme.com/x", "acme.com")
    assert not same_site("https://notacme.com/x", "acme.com")
    assert not same_site("https://acme.com.evil.test/x", "acme.com")


def test_html_to_text_drops_scripts_and_keeps_line_structure():
    html = "<body><h3>Priya Raman</h3><p>CEO</p><script>var x=1</script><style>a{}</style></body>"
    text = html_to_text(html)
    assert "var x" not in text and "a{}" not in text
    # Line structure matters: extractors pair a name with the title beneath it.
    assert text.splitlines() == ["Priya Raman", "CEO"]


@pytest.mark.parametrize(
    "url,anchor,role",
    [
        ("https://a.com/pricing", "Pricing", "pricing"),
        ("https://a.com/about-us", "", "about"),
        ("https://a.com/careers", "Careers", "careers"),
        ("https://a.com/privacy-policy", "", "legal"),
        ("https://a.com/case-studies", "", "customers"),
        ("https://a.com/security", "Trust", "security"),
    ],
)
def test_classify_recognises_standard_pages(url, anchor, role):
    assert classify(url, anchor)[0] == role


def test_classify_prefers_url_over_anchor_text():
    # A "Learn more" link pointing at /pricing is still the pricing page.
    assert classify("https://a.com/pricing", "Learn more")[0] == "pricing"


def test_classify_prefers_shallow_paths():
    shallow = classify("https://a.com/careers", "")[1]
    deep = classify("https://a.com/careers/eng/senior-backend", "")[1]
    assert shallow > deep


def test_links_from_skips_offsite_and_asset_links(saas_pages):
    home = saas_pages[0]
    urls = [url for url, _anchor in links_from(home, "kettlewind.test")]
    assert "https://kettlewind.test/pricing" in urls
    assert not any("linkedin.com" in url for url in urls)
    assert not any(url.endswith(".svg") for url in urls)
