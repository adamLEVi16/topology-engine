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
import ipaddress
import json
import logging
import re
import socket
import time
import urllib.robotparser
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from .browser import Renderer
from .config import Config
from .models import Page

log = logging.getLogger("dealscope.fetch")

_STRIP_TAGS = ("script", "style", "noscript", "svg", "template", "iframe")


# --- URL helpers -----------------------------------------------------------


# Marketplaces where businesses are *listed*. Only the host survives
# normalisation, so pasting a listing URL used to analyse the marketplace
# itself and return a confident, well-formatted brief about BizBuySell —
# silently, with no hint that the wrong thing had been read.
LISTING_VENUES = {
    "bizbuysell.com", "bizquest.com", "businessesforsale.com", "bizben.com",
    "dealstream.com", "loopnet.com", "businessbroker.net", "sunbeltnetwork.com",
    "murphybusiness.com", "transworldma.com", "flippa.com", "acquire.com",
    "microacquire.com", "empireflippers.com", "quietlight.com", "latonas.com",
    "bizbe.com", "routesforsale.net", "vendedroutes.com",
}


def is_listing_venue(host: str) -> bool:
    """Is this a marketplace rather than a company's own site?"""
    host = (host or "").lower().lstrip(".")
    return any(host == venue or host.endswith("." + venue) for venue in LISTING_VENUES)


def normalize_domain(raw: str) -> str:
    """Turn user input (``Acme.com``, ``https://acme.com/x?y``) into a host."""
    value = (raw or "").strip()
    if not value:
        raise ValueError("empty domain")
    if "://" not in value:
        value = "https://" + value
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError(f"could not parse a hostname from {raw!r}")
    # Refuse rather than quietly analyse the wrong company. A bare marketplace
    # domain is a legitimate thing to look at; a *listing* on one is not — and
    # a listing is addressed by path, query, or fragment depending on the
    # venue, so checking the path alone let ?listing=… straight through.
    deep = bool(parsed.path.strip("/") or parsed.query or parsed.fragment)
    if is_listing_venue(host) and deep:
        raise ValueError(
            f"{raw!r} looks like a listing on {host}, not a company's own site. "
            "This tool reads a business's own website — analysing this URL would "
            f"produce a brief about {host} itself. Use the seller's own domain, "
            "or --usdot for a carrier record."
        )
    return host


def root_url(domain: str, scheme: str = "https") -> str:
    return f"{scheme}://{domain}/"


class BlockedHost(ValueError):
    """A host that resolves somewhere this tool must not reach."""


def check_public_host(host: str) -> None:
    """Refuse hosts that resolve to loopback, private, or link-local addresses.

    The web UI analyses whatever domain a visitor types, so without this the
    server is an open proxy into its own network: cloud metadata endpoints,
    internal admin panels, and localhost services would all be fetched and
    their contents printed into a brief. Checked before the first request and
    again after every redirect, because a public domain can redirect inward.
    """
    if not host:
        raise BlockedHost("no host to check")

    try:
        resolved = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise BlockedHost(f"{host} does not resolve ({exc.strerror or exc})") from exc

    for family, _type, _proto, _canon, sockaddr in resolved:
        if family not in (socket.AF_INET, socket.AF_INET6):
            continue
        try:
            address = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            raise BlockedHost(
                f"{host} resolves to {address}, which is a private or "
                "internal address; dealscope only reads public sites"
            )


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


_META_CHARSET = re.compile(
    rb"""<meta[^>]+charset\s*=\s*["']?\s*([\w.:-]+)""", re.I
)


def decode_html(raw: bytes, content_type: str, header_encoding: str | None) -> str:
    """Decode a page, preferring what the document declares about itself.

    ``requests`` reports ISO-8859-1 for ``text/html`` with no charset parameter,
    per the old HTTP spec, so a UTF-8 page that declares its encoding only in
    markup came out as mojibake — every accented name mangled, and the euro
    sign broken badly enough that prices stopped matching and the brief
    reported "pricing not published". An invented absence is the worst kind.
    """
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig", errors="replace")

    encoding = header_encoding if "charset=" in (content_type or "").lower() else None
    if not encoding:
        declared = _META_CHARSET.search(raw[:4096])
        if declared:
            encoding = declared.group(1).decode("ascii", errors="ignore")
    if not encoding:
        # Nothing said anything. UTF-8 is the safe modern default, and its
        # decoder rejects most Latin-1 text rather than mangling it silently.
        encoding = "utf-8"

    try:
        return raw.decode(encoding, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


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
        self._delays: dict[str, float] = {}
        self.notes: list[str] = []
        self.robots_blocked: list[str] = []
        self.fetch_count = 0
        self.render_count = 0

        # Rendering stays off until somebody asks for it; constructing the
        # renderer is cheap because the browser starts lazily.
        self.renderer: Renderer | None = None
        if self.config.use_js:
            self.renderer = Renderer(
                timeout=self.config.timeout,
                user_agent=self.config.user_agent,
                wait_ms=self.config.js_wait_ms,
                ignore_https_errors=not self.config.verify_tls,
            )

        if self.config.use_cache:
            prune_cache(self.config.cache_dir, self.config.cache_ttl, self.config.cache_max_bytes)

    # -- politeness --

    def _wait(self, host: str, delay: float | None = None) -> None:
        wait_for = self.config.delay if delay is None else delay
        last = self._last_hit.get(host)
        if last is not None:
            gap = wait_for - (time.monotonic() - last)
            if gap > 0:
                time.sleep(gap)
        self._last_hit[host] = time.monotonic()

    def _guard_host(self, url: str) -> None:
        """Raise :class:`BlockedHost` unless this URL may be fetched."""
        if self.config.allow_private_hosts:
            return
        # Note: resolution here is independent of the socket the connection
        # later uses, so DNS rebinding is not defeated by this check alone.
        check_public_host(urlparse(url).hostname or "")

    def delay_for(self, url: str) -> float:
        """Seconds to wait between requests to this host.

        ``robots.txt`` may ask for more than our default via ``Crawl-delay`` or
        ``Request-rate``. Asking is the site's prerogative, so the larger of the
        two values wins.
        """
        parts = urlparse(url)
        key = f"{parts.scheme}://{parts.netloc}"
        if key in self._delays:
            return self._delays[key]

        delay = self.config.delay
        parser = self._robots_for(url)
        if parser is not None:
            requested: list[float] = []
            try:
                value = parser.crawl_delay(self.config.user_agent)
                if value:
                    requested.append(float(value))
            except Exception:
                pass
            try:
                rate = parser.request_rate(self.config.user_agent)
                if rate and rate.requests:
                    requested.append(float(rate.seconds) / float(rate.requests))
            except Exception:
                pass
            if requested:
                asked = max(requested)
                if asked > delay:
                    delay = min(asked, self.config.max_crawl_delay)
                    self.notes.append(
                        f"{parts.netloc} requests a {asked:g}s crawl delay via robots.txt; "
                        f"using {delay:g}s between requests"
                    )

        self._delays[key] = delay
        return delay

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
        # A permissive CLI run must not seed the cache for a later serve().
        scope = "private|" if self.config.allow_private_hosts else ""
        digest = hashlib.sha256((scope + url).encode("utf-8")).hexdigest()[:24]
        # Strip path separators and dot-runs: a host of ".." would otherwise
        # write outside the directory prune_cache manages.
        host = re.sub(r"[^a-z0-9.-]+", "_", (urlparse(url).hostname or "unknown").lower())
        host = re.sub(r"\.{2,}", ".", host).strip("._-") or "unknown"
        return self.config.cache_dir / host / f"{digest}.json"

    def _read_cache(self, key: str) -> Page | None:
        if not self.config.use_cache:
            return None
        # Rendered copies are cached under "<url>|js"; the page itself keeps the
        # plain URL.
        url = key.split("|", 1)[0]
        path = self._cache_path(key)
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
            rendered=data.get("rendered", False),
        )

    def _write_cache(self, key: str, page: Page) -> None:
        if not self.config.use_cache or not page.ok:
            return
        path = self._cache_path(key)
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
                        "rendered": page.rendered,
                    }
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            log.debug("could not cache %s: %s", key, exc)

    # -- fetching --

    def get(self, url: str, role: str = "other", force_render: bool = False) -> Page:
        """Fetch one HTML page. Never raises; failures come back on ``Page.error``.

        When ``force_render`` is set — or when the served HTML comes back too
        thin to be the whole page — the page is re-rendered in a headless
        browser, if one is available.
        """
        url = clean_url(url)
        if not url:
            return Page(url=url, role=role, error="unsupported URL scheme")

        cache_key = url + "|js" if force_render else url
        cached = self._read_cache(cache_key)
        if cached is not None:
            cached.role = role
            return cached

        # Before allowed(), which fetches robots.txt from the same host — a
        # blocked address was still receiving that one unchecked request.
        try:
            self._guard_host(url)
        except BlockedHost as exc:
            self.notes.append(str(exc))
            return Page(url=url, role=role, error=str(exc))

        if not self.allowed(url):
            self.notes.append(f"robots.txt disallows {url}")
            self.robots_blocked.append(url)
            return Page(url=url, role=role, error="disallowed by robots.txt")

        host = urlparse(url).netloc

        delay = self.delay_for(url)
        last_error = "unknown error"

        for attempt in range(self.config.retries + 1):
            try:
                self._wait(host, delay)
                self.fetch_count += 1
                resp = self.session.get(
                    url,
                    timeout=self.config.timeout,
                    verify=self.config.verify_tls,
                    allow_redirects=True,
                    stream=True,
                )

                # The server is explicitly asking us to slow down. Honour the
                # interval it named rather than guessing with backoff.
                if resp.status_code in (429, 503) and attempt < self.config.retries:
                    pause = self._retry_after(resp.headers.get("Retry-After"), attempt)
                    resp.close()
                    self.notes.append(
                        f"{host} returned HTTP {resp.status_code}; waiting {pause:g}s as asked"
                    )
                    time.sleep(pause)
                    continue

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
                html = decode_html(raw, ctype, resp.encoding)

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

                try:
                    self._guard_host(page.final_url)
                except BlockedHost as exc:
                    self.notes.append(f"redirected into a blocked address: {exc}")
                    return Page(url=url, role=role, error=str(exc))

                page.text = html_to_text(html)
                page.title = page_title(html)

                if force_render or self._looks_thin(page):
                    # Called even when no renderer exists, so the brief records
                    # that a thin page went unread rather than staying silent.
                    self._render_into(page, force=force_render)

                self._write_cache(cache_key, page)
                return page

            except requests.RequestException as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < self.config.retries:
                    time.sleep(2**attempt)

        return Page(url=url, role=role, error=last_error)

    def _retry_after(self, header: str | None, attempt: int) -> float:
        """Seconds to wait, from a ``Retry-After`` header if the server sent one."""
        fallback = float(2**attempt)
        if not header:
            return fallback
        header = header.strip()
        try:
            return max(0.0, min(float(header), self.config.max_retry_after))
        except ValueError:
            pass
        try:
            when = parsedate_to_datetime(header)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            seconds = (when - datetime.now(timezone.utc)).total_seconds()
            return max(0.0, min(seconds, self.config.max_retry_after))
        except (TypeError, ValueError):
            return fallback

    def _looks_thin(self, page: Page) -> bool:
        """Does this page look like a shell whose content arrives via JavaScript?"""
        words = len(page.text.split())
        # Count parsed anchors, not occurrences of "<a " in the source: a shell
        # page often carries its whole nav as a string inside a <script>, which
        # would otherwise read as link-rich.
        links = len(make_soup(page.html).find_all("a", href=True))
        return words < 250 or links < 15

    def _render_into(self, page: Page, force: bool = False) -> None:
        """Replace a page's HTML with a browser-rendered version, if we can."""
        if self.renderer is None or not self.renderer.possible:
            # Say so. A brief built without a browser must record that the
            # site's client-rendered parts went unread, not stay silent.
            reason = self.renderer.reason if self.renderer else "rendering is disabled"
            note = f"headless rendering unavailable: {reason}"
            if note not in self.notes:
                self.notes.append(note)
            return
        rendered = self.renderer.render(page.final_url or page.url)
        if not rendered:
            if self.renderer.reason:
                self.notes.append(f"headless rendering unavailable: {self.renderer.reason}")
            return
        # Only accept the render if it actually recovered something.
        if force or len(rendered) > len(page.html) * 1.1:
            page.html = rendered
            page.text = html_to_text(rendered)
            page.title = page_title(rendered) or page.title
            page.rendered = True
            self.render_count += 1

    def post(self, url: str, data: dict[str, str], role: str = "other") -> Page:
        """POST a form and return the response page.

        Needed because some public records systems — FMCSA's name search among
        them — only accept searches as form posts. Same politeness rules apply:
        robots is checked, the host delay is honoured, and the response is
        cached under a key that includes the submitted fields.
        """
        url = clean_url(url)
        if not url:
            return Page(url=url, role=role, error="unsupported URL scheme")

        try:
            self._guard_host(url)
        except BlockedHost as exc:
            self.notes.append(str(exc))
            return Page(url=url, role=role, error=str(exc))

        cache_key = url + "|POST|" + urlencode(sorted(data.items()))
        cached = self._read_cache(cache_key)
        if cached is not None:
            cached.role = role
            return cached

        if not self.allowed(url):
            self.notes.append(f"robots.txt disallows {url}")
            self.robots_blocked.append(url)
            return Page(url=url, role=role, error="disallowed by robots.txt")

        try:
            self._wait(urlparse(url).netloc, self.delay_for(url))
            self.fetch_count += 1
            resp = self.session.post(
                url,
                data=data,
                timeout=self.config.timeout,
                verify=self.config.verify_tls,
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            return Page(url=url, role=role, error=f"{type(exc).__name__}: {exc}")

        page = Page(
            url=url,
            final_url=str(resp.url),
            status=resp.status_code,
            role=role,
            html=resp.text[: self.config.max_bytes],
            headers={k.lower(): v for k, v in resp.headers.items()},
            fetched_at=datetime.now(timezone.utc),
        )
        if page.status >= 400:
            page.error = f"HTTP {page.status}"
            return page

        page.text = html_to_text(page.html)
        page.title = page_title(page.html)
        self._write_cache(cache_key, page)
        return page

    def get_text(self, url: str) -> str:
        """Fetch a non-HTML resource (sitemaps) as text; empty string on failure.

        Sitemap roots come from the target's own robots.txt, so a site can name
        any address it likes here. The host is checked like any other.
        """
        try:
            self._guard_host(url)
        except BlockedHost as exc:
            self.notes.append(str(exc))
            return ""
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
        if self.renderer is not None:
            self.renderer.close()


def prune_cache(cache_dir: Path, ttl: int, max_bytes: int) -> int:
    """Delete expired cache entries, then trim to ``max_bytes``, oldest first.

    Entries were previously only ignored once stale, never removed, so the
    directory grew without limit. Returns the number of files deleted.
    """
    try:
        if not cache_dir.exists():
            return 0
        entries: list[tuple[float, int, Path]] = []
        for path in cache_dir.rglob("*.json"):
            try:
                stat = path.stat()
            except OSError:
                continue
            entries.append((stat.st_mtime, stat.st_size, path))
    except OSError:
        return 0

    removed = 0
    cutoff = time.time() - ttl
    surviving: list[tuple[float, int, Path]] = []
    for mtime, size, path in entries:
        if mtime < cutoff:
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
        else:
            surviving.append((mtime, size, path))

    total = sum(size for _m, size, _p in surviving)
    if total > max_bytes:
        for mtime, size, path in sorted(surviving):  # oldest first
            if total <= max_bytes:
                break
            try:
                path.unlink()
                total -= size
                removed += 1
            except OSError:
                pass

    return removed
