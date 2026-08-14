"""Shared readers for structured metadata.

Publishers hand out a lot for free in JSON-LD and Open Graph tags. Those are
the highest-confidence sources available without an API, so they are read
first and everything else is treated as a fallback.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable

from ..fetch import make_soup
from ..models import Page


def json_ld_objects(html: str) -> list[dict[str, Any]]:
    """Every JSON-LD object on a page, with ``@graph`` containers flattened."""
    soup = make_soup(html)
    out: list[dict[str, Any]] = []

    for tag in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        raw = tag.string or tag.get_text() or ""
        if not raw.strip():
            continue
        # Some CMSs emit trailing commas or HTML comments inside the block.
        cleaned = re.sub(r"^\s*<!--|-->\s*$", "", raw.strip())
        try:
            data = json.loads(cleaned)
        except ValueError:
            try:
                data = json.loads(re.sub(r",\s*([}\]])", r"\1", cleaned))
            except ValueError:
                continue
        _flatten(data, out)

    return out


def _flatten(node: Any, out: list[dict[str, Any]]) -> None:
    if isinstance(node, list):
        for item in node:
            _flatten(item, out)
    elif isinstance(node, dict):
        if "@graph" in node:
            _flatten(node["@graph"], out)
        if any(key != "@graph" for key in node):
            out.append(node)


def of_type(objects: Iterable[dict[str, Any]], *types: str) -> list[dict[str, Any]]:
    """JSON-LD objects whose ``@type`` matches any of ``types`` (case-insensitive)."""
    wanted = {t.lower() for t in types}
    found = []
    for obj in objects:
        raw = obj.get("@type") or obj.get("type") or ""
        values = raw if isinstance(raw, list) else [raw]
        if any(str(v).lower() in wanted for v in values):
            found.append(obj)
    return found


def meta_tags(html: str) -> dict[str, str]:
    """``name``/``property`` meta tags plus ``<title>``, lowercased keys."""
    soup = make_soup(html)
    tags: dict[str, str] = {}

    for tag in soup.find_all("meta"):
        key = tag.get("property") or tag.get("name") or tag.get("itemprop")
        value = tag.get("content")
        if key and value:
            key = key.strip().lower()
            if key not in tags:
                tags[key] = " ".join(value.split())

    if soup.title and soup.title.string:
        tags.setdefault("title", " ".join(soup.title.string.split()))

    canonical = soup.find("link", rel=lambda v: v and "canonical" in str(v).lower())
    if canonical and canonical.get("href"):
        tags["canonical"] = canonical["href"].strip()

    return tags


def text_of(value: Any) -> str:
    """Coerce a JSON-LD value (string, list, or nested object) to plain text."""
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, list):
        for item in value:
            got = text_of(item)
            if got:
                return got
        return ""
    if isinstance(value, dict):
        for key in ("name", "@value", "value", "text", "url"):
            if key in value:
                return text_of(value[key])
    return ""


def pages_by_role(pages: Iterable[Page], *roles: str) -> list[Page]:
    wanted = set(roles)
    return [p for p in pages if p.ok and p.role in wanted]


def joined_text(pages: Iterable[Page], limit: int = 60_000) -> str:
    parts: list[str] = []
    total = 0
    for page in pages:
        if not page.ok:
            continue
        chunk = page.text[: limit - total]
        parts.append(chunk)
        total += len(chunk)
        if total >= limit:
            break
    return "\n".join(parts)
