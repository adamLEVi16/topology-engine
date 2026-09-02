"""The whole-project audit: ten findings, each asserted in both directions."""

from __future__ import annotations

import pathlib
import tempfile
from datetime import datetime, timezone

import pytest

from dealscope.analyzer import state_from_address
from dealscope.fetch import html_to_text, make_soup, page_title
from dealscope.models import Page


def _page(html: str, url: str = "https://a.test/", role: str = "home") -> Page:
    return Page(url=url, final_url=url, status=200, role=role, html=html,
                text=html_to_text(html), title=page_title(html), headers={},
                fetched_at=datetime.now(timezone.utc))


# --- #2: a trailing country is not a state ---


def test_a_structured_us_address_yields_its_state_not_its_country():
    """schema.org addresses end in addressCountry. Reading "US" as the state
    penalised every FMCSA candidate and refused perfect name matches — on
    exactly the sites careful enough to publish structured data."""
    assert state_from_address("14 Mill Lane, Dayton, OH, 45402, US") == "OH"
    assert state_from_address("14 Mill Lane, Dayton, OH 45402, USA") == "OH"
    assert state_from_address("Dayton, OH, United States") == "OH"
    # Plain forms unchanged.
    assert state_from_address("Columbus, OH 43004-1234") == "OH"
    # No state present stays empty — not "US", not a guess.
    assert state_from_address("Dayton, US") == ""
    assert state_from_address("London, UK") == "UK" or state_from_address("London, UK") == ""


def test_jsonld_location_prefers_region_over_country():
    from dealscope.extract import contact

    page = _page('''<html><head><script type="application/ld+json">
    {"@type":"Organization","name":"Acme","address":{"@type":"PostalAddress",
    "addressLocality":"Dayton","addressRegion":"OH","postalCode":"45402","addressCountry":"US"}}
    </script></head><body>hi</body></html>''')
    data, _ = contact.extract([page], "a.test")
    assert data["locations"] == ["Dayton, OH"]
    assert all(state_from_address(c) == "OH" for c in data["addresses"] + data["locations"])


def test_jsonld_location_falls_back_to_country_without_a_region():
    """The mirror: a non-US address with no region still gets its country."""
    from dealscope.extract import contact

    page = _page('''<html><head><script type="application/ld+json">
    {"@type":"Organization","name":"Acme","address":{"@type":"PostalAddress",
    "addressLocality":"Bristol","addressCountry":"GB"}}</script></head><body>hi</body></html>''')
    data, _ = contact.extract([page], "a.test")
    assert data["locations"] == ["Bristol, GB"]


# --- #10: a footer is a footer, whatever its wrapper is called ---


def test_a_phone_in_a_footer_nav_is_not_in_the_header():
    from dealscope.extract.contact import _in_site_header

    footer = make_soup('<body><footer><div class="footer-nav-links">'
                       '<a href="tel:+15551234567">x</a></div></footer></body>')
    assert _in_site_header(footer.find("a")) is False
    nested = make_soup('<body><footer><nav><a href="tel:+15551234567">x</a></nav></footer></body>')
    assert _in_site_header(nested.find("a")) is False
    # Mirror: a genuine masthead still counts, by tag and by class.
    header = make_soup('<body><header><a href="tel:+15551234567">x</a></header></body>')
    assert _in_site_header(header.find("a")) is True
    classed = make_soup('<body><div class="site-nav"><a href="tel:+15551234567">x</a></div></body>')
    assert _in_site_header(classed.find("a")) is True


# --- #9: a locale prefix is only a duplicate when a twin exists ---


def test_a_site_served_entirely_under_a_locale_keeps_its_navigation():
    from dealscope.discovery import _looks_localised

    known = {"/en/about", "/en/pricing", "/en/contact"}
    assert _looks_localised("https://a.test/en/about", known) is False
    # Mirror: with an un-prefixed twin present it IS a duplicate.
    known_with_twin = {"/about", "/en/about"}
    assert _looks_localised("https://a.test/en/about", known_with_twin) is True
    # Legacy call without a link set keeps the old conservative behaviour.
    assert _looks_localised("https://a.test/fr/about") is True


# --- #5 / #6: the CLI ---


def test_a_swallowed_internal_failure_is_a_nonzero_exit(monkeypatch):
    from dealscope import cli
    from dealscope.analyzer import _failed_brief

    monkeypatch.setattr(cli, "analyze", lambda d, c, progress=None: _failed_brief(d, "boom"))
    args = cli._build_parser().parse_args(["analyze", "x.test", "-q"])
    assert cli._run_analyze(args) == 1


def test_a_single_domain_into_a_directory_writes_a_named_file(monkeypatch):
    from dealscope import cli
    from dealscope.analyzer import _failed_brief

    monkeypatch.setattr(cli, "analyze", lambda d, c, progress=None: _failed_brief(d, "boom"))
    out = pathlib.Path(tempfile.mkdtemp())
    args = cli._build_parser().parse_args(["analyze", "x.test", "-f", "json", "-o", str(out), "-q"])
    cli._run_analyze(args)  # used to raise IsADirectoryError here
    assert (out / "x.test.json").exists()


# --- #3: redirects are guarded before they are followed ---


class _Resp:
    def __init__(self, status, headers=None, url=""):
        self.status_code, self.headers, self.url = status, headers or {}, url
        self.is_redirect = status in (301, 302, 303, 307, 308) and "Location" in self.headers
        self.is_permanent_redirect = status in (301, 308) and "Location" in self.headers
        self.encoding, self.content, self.text = "utf-8", b"", ""
    def close(self): pass
    def iter_content(self, n): return iter([b"<html>x</html>"])


def test_a_redirect_into_a_private_address_is_never_requested(monkeypatch):
    """allow_redirects=True let requests fetch the internal target before the
    post-redirect guard ran. Now each hop is checked before it is issued."""
    from dealscope.config import Config
    from dealscope.fetch import Fetcher

    requested: list[str] = []
    f = Fetcher(Config(use_cache=False, respect_robots=False))
    f._delays = {}

    def fake_request(method, url, allow_redirects=False, **kw):
        requested.append(url)
        if url.startswith("https://public.test/"):
            return _Resp(302, {"Location": "http://127.0.0.1:8765/admin"}, url)
        return _Resp(200, {"Content-Type": "text/html"}, url)

    monkeypatch.setattr(f.session, "request", fake_request)
    monkeypatch.setattr(f, "_wait", lambda *a, **k: None)
    monkeypatch.setattr("dealscope.fetch.check_public_host",
                        lambda h: (_ for _ in ()).throw(__import__("dealscope.fetch", fromlist=["BlockedHost"]).BlockedHost(f"{h} is private")) if h.startswith("127.") else None)

    page = f.get("https://public.test/")
    assert page.error and "127.0.0.1" in page.error
    # The loopback hop was never issued. robots.txt and the page itself are fine.
    assert not any("127.0.0.1" in u for u in requested), requested


def test_a_public_redirect_chain_is_still_followed(monkeypatch):
    """The mirror: ordinary redirects keep working and final_url is the last hop."""
    from dealscope.config import Config
    from dealscope.fetch import Fetcher

    f = Fetcher(Config(use_cache=False, respect_robots=False))
    hops = {"https://a.test/": "https://www.a.test/", "https://www.a.test/": None}

    def fake_request(method, url, allow_redirects=False, **kw):
        nxt = hops.get(url)
        return _Resp(301, {"Location": nxt}, url) if nxt else _Resp(200, {"Content-Type": "text/html"}, url)

    monkeypatch.setattr(f.session, "request", fake_request)
    monkeypatch.setattr(f, "_wait", lambda *a, **k: None)
    monkeypatch.setattr("dealscope.fetch.check_public_host", lambda h: None)
    page = f.get("https://a.test/")
    assert page.ok and page.final_url == "https://www.a.test/"


# --- #4: thin means thin on both counts ---


def test_a_small_real_page_is_not_re_rendered():
    from dealscope.config import Config
    from dealscope.fetch import Fetcher

    f = Fetcher(Config(use_cache=False))
    nav = "".join(f'<a href="/p{i}">Page {i}</a>' for i in range(8))
    real = _page(f"<body><nav>{nav}</nav><p>{'word ' * 400}</p></body>")
    assert f._looks_thin(real) is False           # 8 links, 400 words: a real small page
    shell = _page("<body><div id='root'></div><a href='/'>Home</a></body>")
    assert f._looks_thin(shell) is True           # the mirror: a JS shell still renders


# --- #7: a failed forced render does not poison the render cache ---


def test_a_failed_forced_render_is_not_cached_as_rendered(monkeypatch):
    from dealscope.config import Config
    from dealscope.fetch import Fetcher

    f = Fetcher(Config(use_cache=True, respect_robots=False, cache_dir=pathlib.Path(tempfile.mkdtemp())))
    monkeypatch.setattr(f.session, "request",
                        lambda m, u, allow_redirects=False, **k: _Resp(200, {"Content-Type": "text/html"}, u))
    monkeypatch.setattr(f, "_wait", lambda *a, **k: None)
    monkeypatch.setattr("dealscope.fetch.check_public_host", lambda h: None)

    class NoBrowser:
        possible, reason = True, "crashed"
        def render(self, url, host_ok=None): return None
    f.renderer = NoBrowser()

    page = f.get("https://a.test/", force_render=True)
    assert page.ok and page.rendered is False
    assert f._read_cache("https://a.test/|js") is None       # not poisoned
    assert f._read_cache("https://a.test/") is not None        # plain copy kept


# --- #1: the browser refuses to land on a private host ---


def test_render_discards_a_page_that_navigated_to_a_blocked_host(monkeypatch):
    from dealscope import browser as b

    class FakePage:
        url = "http://127.0.0.1:8765/"
        def route(self, *a, **k): pass
        def goto(self, *a, **k): pass
        def wait_for_timeout(self, *a): pass
        def content(self): return "<html>internal</html>"
        def close(self): pass
    class FakeCtx:
        def new_page(self): return FakePage()
        def close(self): pass
    class FakeBrowser:
        def new_context(self, **k): return FakeCtx()

    r = b.Renderer.__new__(b.Renderer)
    r._browser, r.user_agent, r.ignore_https_errors = FakeBrowser(), "", False
    r.timeout, r.wait_ms, r.render_count = 5, 0, 0
    monkeypatch.setattr(r, "_ensure_browser", lambda: True)

    blocked = r.render("https://public.test/", host_ok=lambda h: not h.startswith("127."))
    assert blocked is None
    # Mirror: a page that stays public is returned.
    FakePage.url = "https://public.test/"
    assert r.render("https://public.test/", host_ok=lambda h: True) == "<html>internal</html>"
