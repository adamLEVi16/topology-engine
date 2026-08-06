"""A small local web UI: paste a domain, read the brief.

Built on the standard library's HTTP server so the tool stays installable with
no web framework. It binds to localhost by default and holds no state beyond
the on-disk fetch cache.
"""

from __future__ import annotations

import html
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .analyzer import analyze
from .config import Config
from .render.html import render_index, to_html

log = logging.getLogger("dealscope.web")

# One analysis at a time. Each run makes real requests to somebody's website,
# and a shared lock keeps an impatient reload from doubling that traffic.
_analysis_lock = threading.Lock()


class BriefHandler(BaseHTTPRequestHandler):
    server_version = "dealscope"
    config: Config = Config()

    def log_message(self, fmt: str, *args) -> None:  # quieter default logging
        log.info("%s - %s", self.address_string(), fmt % args)

    def _send(self, body: str, status: int = 200) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        parts = urlparse(self.path)

        if parts.path == "/healthz":
            self._send("ok")
            return
        if parts.path != "/":
            self._send(render_index(error="Not found."), status=404)
            return

        query = parse_qs(parts.query)
        domain = (query.get("domain", [""])[0] or "").strip()
        fresh = query.get("fresh", [""])[0] == "1"

        if not domain:
            self._send(render_index(fresh=fresh))
            return

        config = Config(**{**vars(self.config), "use_cache": self.config.use_cache and not fresh})

        try:
            with _analysis_lock:
                brief = analyze(domain, config)
        except ValueError as exc:
            self._send(
                render_index(error=f"Could not read that: {html.escape(str(exc))}", domain=domain),
                status=400,
            )
            return
        except Exception as exc:  # keep the server alive on unexpected failures
            log.exception("analysis failed for %s", domain)
            self._send(
                render_index(
                    error=f"Analysis failed: {html.escape(type(exc).__name__)}. "
                    "Check the server log for details.",
                    domain=domain,
                ),
                status=500,
            )
            return

        self._send(to_html(brief, show_form=True, domain=domain, fresh=fresh))


def serve(host: str = "127.0.0.1", port: int = 8765, config: Config | None = None) -> None:
    BriefHandler.config = config or Config()
    server = ThreadingHTTPServer((host, port), BriefHandler)
    shown = host if host != "0.0.0.0" else "localhost"  # noqa: S104 - user's explicit choice
    print(f"dealscope is running at http://{shown}:{port}  (ctrl-c to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        server.server_close()
