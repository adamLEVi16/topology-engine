"""A small local web UI: paste a domain, read the brief.

Built on the standard library's HTTP server so the tool stays installable with
no web framework. It binds to localhost by default and holds no state beyond
the on-disk fetch cache and a short in-memory list of recent jobs.

Analysis runs in a background thread rather than inside the request. A large
site can take a minute at the default one-second-per-request pace, which is far
longer than a browser will sit on a blank page, so the request returns
immediately and the page polls for progress.
"""

from __future__ import annotations

import html
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .analyzer import analyze
from .config import Config
from .models import CompanyBrief
from .render.html import render_index, render_working, to_html

log = logging.getLogger("dealscope.web")

MAX_JOBS = 40

# One analysis at a time. Each run makes real requests to somebody's website,
# and a shared lock keeps an impatient reload from doubling that traffic.
_analysis_lock = threading.Lock()


@dataclass
class Job:
    id: str
    domain: str
    fresh: bool = False
    status: str = "running"  # running | done | error
    progress: str = "Starting…"
    brief: CompanyBrief | None = None
    error: str = ""
    started_at: float = field(default_factory=time.monotonic)

    @property
    def elapsed(self) -> int:
        return int(time.monotonic() - self.started_at)


class JobStore:
    """Recent jobs, kept in memory and trimmed to a fixed size."""

    def __init__(self, limit: int = MAX_JOBS):
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()
        self.limit = limit

    def create(self, domain: str, fresh: bool) -> Job:
        job = Job(id=uuid.uuid4().hex[:16], domain=domain, fresh=fresh)
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
            while len(self._order) > self.limit:
                self._jobs.pop(self._order.pop(0), None)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)


_jobs = JobStore()


def _run_job(job: Job, config: Config) -> None:
    """Analyze in the background, recording progress as it goes."""
    try:
        if _analysis_lock.locked():
            job.progress = "Waiting for the current analysis to finish…"
        with _analysis_lock:
            job.progress = f"Fetching {job.domain}…"

            def progress(message: str) -> None:
                job.progress = message

            job.brief = analyze(job.domain, config, progress=progress)
            job.status = "done"
    except ValueError as exc:
        job.status = "error"
        job.error = str(exc)
    except Exception as exc:  # never let a worker thread take down the server
        log.exception("analysis failed for %s", job.domain)
        job.status = "error"
        job.error = f"{type(exc).__name__}: {exc}"


class BriefHandler(BaseHTTPRequestHandler):
    server_version = "dealscope"
    protocol_version = "HTTP/1.1"
    config: Config = Config()

    def log_message(self, fmt: str, *args) -> None:  # quieter default logging
        log.info("%s - %s", self.address_string(), fmt % args)

    def _send(self, body: str, status: int = 200, headers: dict[str, str] | None = None) -> None:
        payload = body.encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(payload)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            # The reader closed the tab or hit reload before we replied. Normal,
            # and not worth a traceback.
            log.info("client disconnected before the response was sent")

    def _redirect(self, location: str) -> None:
        self._send(
            f'<meta http-equiv="refresh" content="0;url={html.escape(location)}">',
            status=303,
            headers={"Location": location},
        )

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        parts = urlparse(self.path)
        query = parse_qs(parts.query)

        if parts.path == "/healthz":
            self._send("ok")
            return

        # --- job status / result ---
        if parts.path.startswith("/job/"):
            job = _jobs.get(parts.path[len("/job/") :])
            if job is None:
                self._send(render_index(error="That job has expired. Try again."), status=404)
                return
            if job.status == "running":
                self._send(render_working(job))
                return
            if job.status == "error":
                self._send(
                    render_index(error=f"Could not read that: {job.error}", domain=job.domain),
                    status=400,
                )
                return
            self._send(to_html(job.brief, show_form=True, domain=job.domain, fresh=job.fresh))
            return

        if parts.path != "/":
            self._send(render_index(error="Not found."), status=404)
            return

        # --- new analysis ---
        domain = (query.get("domain", [""])[0] or "").strip()
        fresh = query.get("fresh", [""])[0] == "1"

        if not domain:
            self._send(render_index(fresh=fresh))
            return

        config = Config(**{**vars(self.config), "use_cache": self.config.use_cache and not fresh})
        job = _jobs.create(domain, fresh)
        threading.Thread(target=_run_job, args=(job, config), daemon=True).start()
        self._redirect(f"/job/{job.id}")


def serve(host: str = "127.0.0.1", port: int = 8765, config: Config | None = None) -> None:
    BriefHandler.config = config or Config()
    server = ThreadingHTTPServer((host, port), BriefHandler)
    shown = host if host != "0.0.0.0" else "localhost"  # noqa: S104 - user's explicit choice
    print(f"dealscope is running at http://{shown}:{port}  (ctrl-c to stop)")
    print("Large sites take 30-60 seconds; the page shows progress while it works.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        server.server_close()
