"""Crawl-delay, Retry-After, and cache pruning."""

from __future__ import annotations

import time
import urllib.robotparser
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest

from dealscope.config import Config
from dealscope.fetch import Fetcher, prune_cache


def _fetcher(**overrides) -> Fetcher:
    base = {"delay": 1.0, "use_cache": False, "use_js": False}
    base.update(overrides)
    return Fetcher(Config(**base))


def _robots(body: str) -> urllib.robotparser.RobotFileParser:
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(body.splitlines())
    return parser


# --- Crawl-delay -----------------------------------------------------------


def test_crawl_delay_from_robots_raises_the_floor(monkeypatch):
    fetcher = _fetcher(delay=1.0)
    monkeypatch.setattr(
        fetcher, "_robots_for", lambda url: _robots("User-agent: *\nCrawl-delay: 7\n")
    )
    try:
        assert fetcher.delay_for("https://slow.test/") == 7.0
        assert any("crawl delay" in note for note in fetcher.notes)
    finally:
        fetcher.close()


def test_a_shorter_crawl_delay_never_speeds_us_up(monkeypatch):
    """Our own floor still applies; robots may slow us, not hurry us."""
    fetcher = _fetcher(delay=2.0)
    monkeypatch.setattr(
        fetcher, "_robots_for", lambda url: _robots("User-agent: *\nCrawl-delay: 0.1\n")
    )
    try:
        assert fetcher.delay_for("https://quick.test/") == 2.0
    finally:
        fetcher.close()


def test_an_extreme_crawl_delay_is_capped(monkeypatch):
    fetcher = _fetcher(delay=1.0, max_crawl_delay=15.0)
    monkeypatch.setattr(
        fetcher, "_robots_for", lambda url: _robots("User-agent: *\nCrawl-delay: 600\n")
    )
    try:
        assert fetcher.delay_for("https://glacial.test/") == 15.0
    finally:
        fetcher.close()


def test_request_rate_is_honoured_too(monkeypatch):
    fetcher = _fetcher(delay=1.0)
    monkeypatch.setattr(
        fetcher, "_robots_for", lambda url: _robots("User-agent: *\nRequest-rate: 1/10\n")
    )
    try:
        assert fetcher.delay_for("https://rated.test/") == 10.0
    finally:
        fetcher.close()


def test_delay_is_resolved_once_per_host(monkeypatch):
    calls: list[str] = []

    fetcher = _fetcher()

    def counting(url):
        calls.append(url)
        return _robots("User-agent: *\nCrawl-delay: 3\n")

    monkeypatch.setattr(fetcher, "_robots_for", counting)
    try:
        fetcher.delay_for("https://a.test/one")
        fetcher.delay_for("https://a.test/two")
        assert len(calls) == 1
    finally:
        fetcher.close()


# --- Retry-After -----------------------------------------------------------


@pytest.mark.parametrize("header,expected", [("5", 5.0), ("0", 0.0), ("12.5", 12.5)])
def test_retry_after_accepts_seconds(header, expected):
    fetcher = _fetcher()
    try:
        assert fetcher._retry_after(header, attempt=0) == expected
    finally:
        fetcher.close()


def test_retry_after_accepts_an_http_date():
    fetcher = _fetcher()
    try:
        when = datetime.now(timezone.utc) + timedelta(seconds=9)
        got = fetcher._retry_after(format_datetime(when), attempt=0)
        assert 7.0 <= got <= 10.0
    finally:
        fetcher.close()


def test_retry_after_is_capped_and_never_negative():
    fetcher = _fetcher(max_retry_after=30.0)
    try:
        assert fetcher._retry_after("99999", attempt=0) == 30.0
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        assert fetcher._retry_after(format_datetime(past), attempt=0) == 0.0
    finally:
        fetcher.close()


def test_retry_after_falls_back_to_backoff_when_absent_or_junk():
    fetcher = _fetcher()
    try:
        assert fetcher._retry_after(None, attempt=2) == 4.0
        assert fetcher._retry_after("soon-ish", attempt=1) == 2.0
    finally:
        fetcher.close()


# --- cache pruning ---------------------------------------------------------


def test_prune_removes_expired_entries(tmp_path):
    fresh = tmp_path / "host" / "fresh.json"
    stale = tmp_path / "host" / "stale.json"
    fresh.parent.mkdir(parents=True)
    fresh.write_text("{}")
    stale.write_text("{}")

    old = time.time() - 10_000
    import os

    os.utime(stale, (old, old))

    removed = prune_cache(tmp_path, ttl=3600, max_bytes=10**9)
    assert removed == 1
    assert fresh.exists() and not stale.exists()


def test_prune_enforces_a_size_cap_oldest_first(tmp_path):
    directory = tmp_path / "host"
    directory.mkdir(parents=True)
    import os

    now = time.time()
    for index in range(5):
        path = directory / f"{index}.json"
        path.write_text("x" * 1000)
        os.utime(path, (now - (5 - index) * 100, now - (5 - index) * 100))

    prune_cache(tmp_path, ttl=10**6, max_bytes=2500)
    survivors = sorted(p.name for p in directory.glob("*.json"))

    assert survivors == ["3.json", "4.json"]  # the two newest


def test_prune_is_silent_when_there_is_no_cache(tmp_path):
    assert prune_cache(tmp_path / "missing", ttl=10, max_bytes=10) == 0
