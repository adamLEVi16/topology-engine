"""Optional headless-browser rendering for client-rendered sites.

A growing share of sites build their navigation and footer in the browser, so
reading the server's HTML alone yields a thin, misleading picture. When
Playwright is available this renders those pages properly.

It is strictly optional and strictly a fallback. If Playwright is not
installed, or its browser binary is missing, rendering is skipped and the
static HTML stands — the brief then says its view was partial rather than
pretending the site was empty.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse
from typing import Callable
import os
from pathlib import Path

log = logging.getLogger("dealscope.browser")

# Where Playwright keeps browsers, and the per-platform shape of the binary.
_BROWSER_GLOBS = (
    "chromium-*/chrome-linux/chrome",
    "chromium-*/chrome-win/chrome.exe",
    "chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium",
    "chromium_headless_shell-*/chrome-linux/headless_shell",
)


def discover_chromium() -> str:
    """Find an installed Chromium that Playwright did not expect.

    Playwright pins an exact browser build, so an image that ships a slightly
    older one fails to launch even though a perfectly good browser is present.
    An explicit path wins; otherwise the browsers directory is searched.
    """
    explicit = os.environ.get("DEALSCOPE_CHROMIUM") or os.environ.get(
        "PLAYWRIGHT_CHROMIUM_EXECUTABLE"
    )
    if explicit and Path(explicit).exists():
        return explicit

    root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if not root:
        return ""
    base = Path(root)
    if not base.is_dir():
        return ""

    for pattern in _BROWSER_GLOBS:
        # Newest build number last, so prefer the highest.
        for match in sorted(base.glob(pattern)):
            if match.exists():
                return str(match)
    return ""

# Skip what we never read anyway. Faster, and far less of the site's bandwidth.
BLOCKED_RESOURCES = ("image", "media", "font")


class Renderer:
    """Lazily-started headless Chromium. Safe to construct unconditionally."""

    def __init__(
        self,
        timeout: float = 20.0,
        user_agent: str = "",
        wait_ms: int = 1200,
        ignore_https_errors: bool = False,
    ):
        self.timeout = timeout
        self.user_agent = user_agent
        self.wait_ms = wait_ms
        self.ignore_https_errors = ignore_https_errors
        self.reason = ""
        # requests honours these automatically; Chromium has to be told, which
        # matters on corporate networks and in proxied CI environments.
        self.proxy = (
            os.environ.get("HTTPS_PROXY")
            or os.environ.get("https_proxy")
            or os.environ.get("HTTP_PROXY")
            or os.environ.get("http_proxy")
            or ""
        )
        self.proxy_bypass = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
        self.render_count = 0
        self._playwright = None
        self._browser = None
        self._start = None

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.reason = (
                "playwright is not installed (pip install 'dealscope[js]' "
                "&& playwright install chromium)"
            )
            return
        self._start = sync_playwright

    @property
    def possible(self) -> bool:
        """True while rendering has not been ruled out."""
        return self._start is not None and not self.reason

    def _ensure_browser(self) -> bool:
        if self._browser is not None:
            return True
        if not self.possible:
            return False
        try:
            self._playwright = self._start().start()
        except Exception as exc:
            self.reason = f"could not start Playwright: {exc}"
            log.info("headless rendering unavailable: %s", self.reason)
            self._shutdown()
            return False

        common: dict = {}
        if self.proxy:
            common["proxy"] = {"server": self.proxy}
            if self.proxy_bypass:
                common["proxy"]["bypass"] = self.proxy_bypass

        attempts: list[dict] = [dict(common)]
        found = discover_chromium()
        if found:
            attempts.append({**common, "executable_path": found})

        last: Exception | None = None
        for options in attempts:
            try:
                self._browser = self._playwright.chromium.launch(headless=True, **options)
                if "executable_path" in options:
                    log.info("using Chromium at %s", options["executable_path"])
                return True
            except Exception as exc:
                last = exc

        # Almost always "browser binary not found" — recoverable, and the
        # caller carries on with static HTML.
        self.reason = (
            f"could not start Chromium ({last}). Run 'playwright install chromium', "
            "or set DEALSCOPE_CHROMIUM to an existing browser."
        )
        log.info("headless rendering unavailable: %s", self.reason)
        self._shutdown()
        return False

    def render(
        self, url: str, host_ok: Callable[[str], bool] | None = None
    ) -> str | None:
        """Fully-rendered HTML for ``url``, or ``None`` if that was not possible.

        ``host_ok`` is asked about every host the page tries to reach, and
        about wherever the page ends up after scripts and redirects have run.
        Without it a page could ``location.replace()`` itself onto a loopback
        port or a metadata address and hand that DOM back as its own content.
        """
        if not self._ensure_browser():
            return None

        context = page = None
        try:
            context = self._browser.new_context(
                user_agent=self.user_agent or None,
                viewport={"width": 1280, "height": 900},
                ignore_https_errors=self.ignore_https_errors,
            )
            page = context.new_page()
            def gate(route):  # noqa: ANN001 - playwright Route
                request = route.request
                if request.resource_type in BLOCKED_RESOURCES:
                    return route.abort()
                if host_ok is not None and not host_ok(urlparse(request.url).hostname or ""):
                    return route.abort()
                return route.continue_()

            page.route("**/*", gate)
            page.goto(url, wait_until="domcontentloaded", timeout=self.timeout * 1000)
            # Give client-side navigation a moment to attach.
            page.wait_for_timeout(self.wait_ms)
            landed = page.url
            if host_ok is not None and not host_ok(urlparse(landed).hostname or ""):
                log.info("render of %s navigated to a blocked host (%s); discarded", url, landed)
                return None
            html = page.content()
            self.render_count += 1
            return html
        except Exception as exc:
            log.info("render failed for %s: %s", url, exc)
            return None
        finally:
            for closable in (page, context):
                try:
                    if closable is not None:
                        closable.close()
                except Exception:
                    pass

    def _shutdown(self) -> None:
        for closable in (self._browser, self._playwright):
            try:
                if closable is not None:
                    closable.close() if closable is self._browser else closable.stop()
            except Exception:
                pass
        self._browser = None
        self._playwright = None

    def close(self) -> None:
        self._shutdown()
