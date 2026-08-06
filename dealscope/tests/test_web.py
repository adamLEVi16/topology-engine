"""The background-job layer behind the web UI."""

from __future__ import annotations

import pytest

from dealscope import web
from dealscope.config import Config
from dealscope.models import CompanyBrief
from dealscope.render.html import render_working


def test_job_store_trims_to_its_limit():
    store = web.JobStore(limit=3)
    jobs = [store.create(f"site{i}.test", False) for i in range(5)]

    assert store.get(jobs[0].id) is None  # oldest evicted
    assert store.get(jobs[4].id) is not None
    assert len(store._order) == 3


def test_job_store_hands_back_distinct_ids():
    store = web.JobStore()
    ids = {store.create("a.test", False).id for _ in range(20)}
    assert len(ids) == 20


def test_run_job_records_progress_then_the_brief(monkeypatch):
    seen: list[str] = []

    def fake_analyze(domain, config, progress=None):
        progress("fetching pricing")
        seen.append(domain)
        return CompanyBrief(domain=domain, name="Fake")

    monkeypatch.setattr(web, "analyze", fake_analyze)
    job = web.Job(id="x", domain="acme.test")
    web._run_job(job, Config())

    assert seen == ["acme.test"]
    assert job.status == "done"
    assert job.progress == "fetching pricing"
    assert job.brief.name == "Fake"


def test_run_job_captures_failures_instead_of_raising(monkeypatch):
    def boom(domain, config, progress=None):
        raise RuntimeError("network gone")

    monkeypatch.setattr(web, "analyze", boom)
    job = web.Job(id="y", domain="acme.test")
    web._run_job(job, Config())  # must not propagate

    assert job.status == "error"
    assert "network gone" in job.error


def test_run_job_reports_a_bad_domain_as_an_error(monkeypatch):
    def bad(domain, config, progress=None):
        raise ValueError("could not parse a hostname")

    monkeypatch.setattr(web, "analyze", bad)
    job = web.Job(id="z", domain="   ")
    web._run_job(job, Config())

    assert job.status == "error"
    assert "hostname" in job.error


def test_working_page_refreshes_itself_and_shows_progress():
    job = web.Job(id="j", domain="acme.test", progress="reading /pricing")
    page = render_working(job)

    assert 'http-equiv="refresh"' in page
    assert "reading /pricing" in page
    assert "acme.test" in page


def test_working_page_escapes_progress_text():
    job = web.Job(id="j", domain="acme.test", progress="<script>alert(1)</script>")
    page = render_working(job)

    assert "<script>alert" not in page
    assert "&lt;script&gt;" in page


@pytest.mark.parametrize("status", ["running", "done", "error"])
def test_job_elapsed_is_always_available(status):
    job = web.Job(id="j", domain="a.test", status=status)
    assert job.elapsed >= 0
