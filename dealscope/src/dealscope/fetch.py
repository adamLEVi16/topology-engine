"""Polite HTTP fetching.

Yes, this is web scraping — of the well-behaved kind. Every request:

* identifies itself with a descriptive User-Agent,
* checks ``robots.txt`` first and skips disallowed paths,
* waits a configurable delay between hits to the same host,
* caps how many bytes it will read,
* is cached on disk so re-running a brief costs the site nothing.

Only publicly served HTML is read. Nothing logs in, submits forms, or tries
to reach anything behind authentication.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import urllib.robotparser
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from .config import Config
from .models import Page

log = logging.getLogger("dealscope.fetch")

_STRIP_TAGS = ("script", "style", "noscript", "svg", "template", "iframe")


# --- URL helpers -----------------------------------------------------------


def normalize_domain(raw: str) -> str:
    """Turn user input (``Acme.com``, ``https://acme.com/x?y``) into a host."""
    value = (raw or "").strip()
    if not value:
        raise ValueError("empty domain")
    if "://" not in value:
        value = "https://" + value
    host = (urlparse(value).hostname or "").lower()
    if not host:
        raise ValueError(f"could not parse a hostname from {raw!r}")
    return host


def root_url(domain: str, scheme: str = "https") -> str:
    return f"{scheme}://{domain}/"


def same_site(url: str, domain: str) -> bool:
    """True when ``url`` belongs to ``domain`` or a subdomain of it."""
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    bare = domain[4:] if domain.startswith("www.") else domain
    return host == domain or host == bare or host.endswith("." + bare)


def clean_url(url: str, base: str = "") -> str:
    """Absolutise, drop fragments, and strip common tracking parameters."""
    if base:
        url = urljoin(base, url)
    parts = urlparse(url)
    if parts.scheme not in ("http", "https"):
        return ""
    query = "&".join(
        piece
        for piece in parts.query.split("&")
        if piece and not piece.lower().startswith(("utm_", "gclid=", "fbclid=", "mc_cid=", "mc_eid="))
    )
    return urlunparse((parts.scheme, parts.netloc, parts.path or "/", "", query, ""))


# --- HTML to text ----------------------------------------------------------


def make_soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:  # lxml missing or malformed markup
        return BeautifulSoup(html, "html.parser")


def html_to_text(html: str) -> str:
    """Visible text, one block element per line.

    Line structure is kept on purpose: downstream extractors read team rosters
    and pricing tables line by line, and flattening everything into one blob
    would destroy the name/title and plan/price pairings.
    """
    soup = make_soup(html)
    for tag in soup(_STRIP_TAGS):
        tag.decompose()
    text = soup.get_text("\n")
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def page_title(html: str) -> str:
    soup = make_soup(html)
    if soup.title and soup.title.string:
        return " ".join(soup.title.string.split())
    h1 = soup.find("h1")
    return " ".join(h1.get_text(" ").split()) if h1 else ""


# --- Fetcher ---------------------------------------------------------------


class Fetcher:
    """Rate-limited, robots-aware, disk-cached HTTP client."""

    def __init__(self, config: Config | None = None):
        self.config = config or Config()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": self.config.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        self._last_hit: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self.notes: list[str] = []
        self.robots_blocked: list[str] = []
        self.fetch_count = 0

    # -- politeness --

    def _wait(self, host: str) -> None:
        last = self._last_hit.get(host)
        if last is not None:
            gap = self.config.delay - (time.monotonic() - last)
            if gap > 0:
                time.sleep(gap)
        self._last_hit[host] = time.monotonic()

    def _robots_for(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        parts = urlparse(url)
        key = f"{parts.scheme}://{parts.netloc}"
        if key in self._robots:
            return self._robots[key]

        parser: urllib.robotparser.RobotFileParser | None = None
        try:
            self._wait(parts.netloc)
            resp = self.session.get(
                key + "/robots.txt",
                timeout=self.config.timeout,
                verify=self.config.verify_tls,
                allow_redirects=True,
            )
            if resp.status_code == 200 and len(resp.content) < 512_000:
                parser = urllib.robotparser.RobotFileParser()
                parser.parse(resp.text.splitlines())
        except requests.RequestException as exc:
            log.debug("robots.txt unavailable for %s: %s", key, exc)

        self._robots[key] = parser
        return parser

    def allowed(self, url: str) -> bool:
        if not self.config.respect_robots:
            return True
        parser = self._robots_for(url)
        if parser is None:
            return True  # no robots.txt served: nothing disallowed
        try:
            return parser.can_fetch(self.config.user_agent, url)
        except Exception:
            return True

    def sitemap_urls(self, url: str) -> list[str]:
        parser = self._robots_for(url)
        if parser is None:
            return []
        try:
            return list(parser.site_maps() or [])
        except Exception:
            return []

    # -- caching --

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
        host = re.sub(r"[^a-z0-9.-]+", "_", (urlparse(url).hostname or "unknown").lower())
        return self.config.cache_dir / host / f"{digest}.json"

    def _read_cache(self, url: str) -> Page | None:
        if not self.config.use_cache:
            return None
        path = self._cache_path(url)
        try:
            if not path.exists():
                return None
            age = time.time() - path.stat().st_mtime
            if age > self.config.cache_ttl:
                return None
            data = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            return None

        return Page(
            url=url,
            final_url=data.get("final_url", url),
            status=data.get("status", 0),
            title=data.get("title", ""),
            html=data.get("html", ""),
            text=data.get("text", ""),
            headers=data.get("headers", {}),
            fetched_at=datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc),
            from_cache=True,
        )

    def _write_cache(self, url: str, page: Page) -> None:
        if not self.config.use_cache or not page.ok:
            return
        path = self._cache_path(url)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "final_url": page.final_url,
                        "status": page.status,
                        "title": page.title,
                        "html": page.html,
                        "text": page.text,
                        "headers": page.headers,
                    }
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            log.debug("could not cache %s: %s", url, exc)

    # -- fetching --

    def get(self, url: str, role: str = "other") -> Page:
        """Fetch one HTML page. Never raises; failures come back on ``Page.error``."""
        url = clean_url(url)
        if not url:
            return Page(url=url, role=role, error="unsupported URL scheme")

        cached = self._read_cache(url)
        if cached is not None:
            cached.role = role
            return cached

        if not self.allowed(url):
            self.notes.append(f"robots.txt disallows {url}")
            self.robots_blocked.append(url)
            return Page(url=url, role=role, error="disallowed by robots.txt")

        host = urlparse(url).netloc
        last_error = "unknown error"
        for attempt in range(self.config.retries + 1):
            try:
                self._wait(host)
                self.fetch_count += 1
                resp = self.session.get(
                    url,
                    timeout=self.config.timeout,
                    verify=self.config.verify_tls,
                    allow_redirects=True,
                    stream=True,
                )
                ctype = resp.headers.get("Content-Type", "")
                if "html" not in ctype and "xml" not in ctype and ctype:
                    resp.close()
                    return Page(url=url, role=role, status=resp.status_code,
                                error=f"non-HTML content ({ctype.split(';')[0]})")

                chunks: list[bytes] = []
                total = 0
                for chunk in resp.iter_content(65_536):
                    chunks.append(chunk)
                    total += len(chunk)
                    if total >= self.config.max_bytes:
                        self.notes.append(f"truncated {url} at {self.config.max_bytes} bytes")
                        break
                resp.close()

                raw = b"".join(chunks)
                encoding = resp.encoding or resp.apparent_encoding or "utf-8"
                html = raw.decode(encoding, errors="replace")

                page = Page(
                    url=url,
                    final_url=str(resp.url),
                    status=resp.status_code,
                    role=role,
                    html=html,
                    headers={k.lower(): v for k, v in resp.headers.items()},
                    fetched_at=datetime.now(timezone.utc),
                )
                if page.status >= 400:
                    page.error = f"HTTP {page.status}"
                    return page

                page.text = html_to_text(html)
                page.title = page_title(html)
                self._write_cache(url, page)
                return page

            except requests.RequestException as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < self.config.retries:
                    time.sleep(2**attempt)

        return Page(url=url, role=role, error=last_error)

    def get_text(self, url: str) -> str:
        """Fetch a non-HTML resource (sitemaps) as text; empty string on failure."""
        try:
            self._wait(urlparse(url).netloc)
            self.fetch_count += 1
            resp = self.session.get(
                url, timeout=self.config.timeout, verify=self.config.verify_tls
            )
            if resp.status_code == 200 and len(resp.content) < self.config.max_bytes:
                return resp.text
        except requests.RequestException as exc:
            log.debug("could not fetch %s: %s", url, exc)
        return ""

    def resolve_home(self, domain: str) -> Page:
        """Fetch the homepage, trying https then http, with and without www."""
        candidates = [
            f"https://{domain}/",
            f"https://www.{domain}/" if not domain.startswith("www.") else f"https://{domain[4:]}/",
            f"http://{domain}/",
        ]
        first: Page | None = None
        for candidate in candidates:
            page = self.get(candidate, role="home")
            if page.ok:
                return page
            if first is None:
                first = page
        return first or Page(url=candidates[0], role="home", error="unreachable")

    def close(self) -> None:
        self.session.close()
