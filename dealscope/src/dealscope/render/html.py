"""Standalone HTML rendering of a brief, shared by the CLI and the web UI."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..config import __version__
from ..extract.commerce import MODEL_LABELS
from ..models import CompanyBrief
from .markdown import DISCLAIMER

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def environment() -> Environment:
    return _env


def brief_context(brief: CompanyBrief, **extra) -> dict:
    """Everything the brief template needs, pre-computed."""
    grouped: dict[str, list[str]] = {}
    for finding in brief.operations.tech:
        grouped.setdefault(finding.category, []).append(finding.name)

    context = {
        "brief": brief,
        "disclaimer": DISCLAIMER,
        "generated": (
            brief.generated_at.strftime("%d %b %Y, %H:%M UTC") if brief.generated_at else "unknown"
        ),
        "narrative_paragraphs": [p for p in brief.narrative.split("\n\n") if p.strip()],
        "model_label": MODEL_LABELS.get(brief.business_model.primary, "unknown"),
        "secondary_labels": [
            MODEL_LABELS.get(s, s) for s in brief.business_model.secondary
        ],
        "tech_by_category": sorted((k, sorted(v)) for k, v in grouped.items()),
        "evidence": brief.all_evidence(),
        "pages_ok": sum(1 for p in brief.pages if not p.get("error")),
        "version": __version__,
    }
    context.update(extra)
    return context


def to_html(brief: CompanyBrief, show_form: bool = False, **extra) -> str:
    template = _env.get_template("brief.html")
    return template.render(**brief_context(brief, show_form=show_form, **extra))


def render_working(job) -> str:
    """The self-refreshing progress page shown while an analysis runs."""
    return _env.get_template("working.html").render(job=job, version=__version__)


def render_index(error: str = "", domain: str = "", fresh: bool = False) -> str:
    template = _env.get_template("index.html")
    return template.render(
        error=error,
        domain=domain,
        fresh=fresh,
        disclaimer=DISCLAIMER,
        version=__version__,
    )
