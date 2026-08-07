"""The headless-render fallback, against a locally served client-rendered page.

These tests use a real HTTP server and a real browser rather than mocks,
because the behaviour worth proving is precisely that a page whose content
arrives via JavaScript comes back complete. When Playwright or its browser is
unavailable the render tests skip, and the degradation test still runs — that
path matters more, since most installs will not have a browser.
"""

from __future__ import annotations

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from dealscope.browser import Renderer, discover_chromium
from dealscope.config import Config
from dealscope.fetch import Fetcher

# Served HTML with an empty shell: every link is attached by script, exactly
# like the footers this fallback exists to recover.
CLIENT_RENDERED = """<!doctype html><html><head><title>Shellco</title></head>
<body><div id="app"></div>
<script>
  document.getElementById('app').innerHTML =
    '<h1>Shellco</h1>' +
    '<p>Shellco builds scheduling software for clinics.</p>' +
    '<nav>' +
    '<a href="/pricing">Pricing</a><a href="/about">About</a>' +
    '<a href="/careers">Careers</a><a href="/contact">Contact</a>' +
    '<a href="/privacy">Privacy Policy</a><a href="/terms">Terms of Service</a>' +
    '</nav>';
</script>
</body></html>"""


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    """A local HTTP server serving the shell page. Returns its base URL."""
    root = tmp_path_factory.mktemp("site")
    (root / "index.html").write_text(CLIENT_RENDERED, encoding="utf-8")

    handler = partial(SimpleHTTPRequestHandler, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(scope="module")
def browser_available() -> bool:
    probe = Renderer(timeout=20.0, user_agent="dealscope-test")
    if not probe.possible:
        probe.close()
        return False
    ok = probe.render("about:blank") is not None
    probe.close()
    return ok


def _config(**overrides) -> Config:
    base = {"delay": 0, "use_cache": False, "timeout": 20.0,
            "allow_private_hosts": True}  # the fixture server is on 127.0.0.1
    base.update(overrides)
    return Config(**base)


def test_static_fetch_sees_an_almost_empty_page(site):
    """Baseline: without rendering, the shell yields nothing useful."""
    fetcher = Fetcher(_config(use_js=False))
    try:
        page = fetcher.get(site)
        assert page.ok
        assert page.rendered is False
        assert "Pricing" not in page.text
        # The anchors exist only as text inside a <script>, so nothing is
        # actually linked yet.
        from dealscope.fetch import make_soup

        assert make_soup(page.html).find_all("a", href=True) == []
    finally:
        fetcher.close()


def test_rendering_recovers_the_client_built_navigation(site, browser_available):
    if not browser_available:
        pytest.skip("no headless browser available")

    fetcher = Fetcher(_config(use_js=True))
    try:
        page = fetcher.get(site, force_render=True)
        assert page.ok
        assert page.rendered is True
        assert "scheduling software for clinics" in page.text
        for label in ("Pricing", "About", "Careers", "Privacy Policy"):
            assert label in page.text
    finally:
        fetcher.close()


def test_thin_pages_are_rendered_without_being_asked(site, browser_available):
    """The shell trips the thin-page check on its own."""
    if not browser_available:
        pytest.skip("no headless browser available")

    fetcher = Fetcher(_config(use_js=True))
    try:
        page = fetcher.get(site)  # no force_render
        assert page.rendered is True
        assert "Pricing" in page.text
    finally:
        fetcher.close()


def test_missing_browser_degrades_instead_of_failing(site, monkeypatch):
    """The path most installs take: no Playwright, no crash, static HTML stands."""
    import dealscope.browser as browser_module

    def no_browser(self):
        self.reason = "could not start Chromium: pretend it is missing"
        return False

    monkeypatch.setattr(browser_module.Renderer, "_ensure_browser", no_browser)

    fetcher = Fetcher(_config(use_js=True))
    try:
        page = fetcher.get(site, force_render=True)
        assert page.ok           # still a usable page
        assert page.rendered is False
        assert any("headless rendering unavailable" in note for note in fetcher.notes)
    finally:
        fetcher.close()


def test_renderer_reports_why_it_cannot_run_when_playwright_is_absent(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "playwright.sync_api", None)
    renderer = Renderer()
    # Either playwright is genuinely absent, or it is present and usable; both
    # are valid, but the object must never claim to work without saying so.
    assert renderer.possible or renderer.reason


def test_discover_chromium_returns_a_real_path_or_nothing():
    found = discover_chromium()
    if found:
        from pathlib import Path

        assert Path(found).exists()
