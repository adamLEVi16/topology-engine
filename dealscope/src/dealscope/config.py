"""Runtime configuration for a dealscope run."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

__version__ = "0.1.0"

DEFAULT_USER_AGENT = (
    f"dealscope/{__version__} (+https://github.com/adamlevi16/topology-engine; "
    "company research bot; contact via repository issues)"
)


def _default_cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(Path.home(), ".cache")
    return Path(base) / "dealscope"


@dataclass
class Config:
    """Knobs for fetching and analysis.

    Defaults are deliberately conservative: one request per second per host,
    robots.txt honoured, a small page budget. This tool reads public pages the
    same way a browser would, and it should stay a good citizen while doing it.
    """

    # Fetching
    max_pages: int = 20
    timeout: float = 12.0
    delay: float = 1.0
    retries: int = 2
    max_bytes: int = 2_500_000
    user_agent: str = DEFAULT_USER_AGENT
    respect_robots: bool = True
    verify_tls: bool = True

    # Private and loopback addresses are refused by default, which is what
    # stops the web UI being an open proxy into its own network. A user running
    # the CLI against their own intranet is a different situation, so it is a
    # deliberate opt-in — never enabled for the server.
    allow_private_hosts: bool = False

    # Politeness ceilings. robots.txt may ask for a long crawl delay; we honour
    # it up to these bounds rather than either ignoring it or stalling forever.
    max_crawl_delay: float = 15.0
    max_retry_after: float = 30.0
    polite_time_budget: float = 120.0

    # Headless rendering (optional; needs the "js" extra plus a browser binary)
    use_js: bool = True
    js_wait_ms: int = 1200

    # Public-records lookups. Off by default: FMCSA covers US motor carriers
    # only, so it is opt-in rather than a cost every analysis pays.
    use_fmcsa: bool = False

    # Caching
    cache_dir: Path = field(default_factory=_default_cache_dir)
    cache_ttl: int = 86_400  # 24h
    cache_max_bytes: int = 200_000_000
    use_cache: bool = True

    # Analysis
    max_people: int = 12
    max_customers: int = 15
    blog_window_days: int = 365

    # Narration
    use_llm: bool = False
    llm_model: str = "claude-sonnet-5"
    llm_api_key: str | None = None

    def resolved_api_key(self) -> str | None:
        return self.llm_api_key or os.environ.get("ANTHROPIC_API_KEY")

    def llm_available(self) -> bool:
        return bool(self.resolved_api_key())
