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

    # Caching
    cache_dir: Path = field(default_factory=_default_cache_dir)
    cache_ttl: int = 86_400  # 24h
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
