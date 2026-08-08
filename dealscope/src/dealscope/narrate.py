"""Write the short summary a buyer actually reads.

The deterministic writer is the default and always runs. It only states things
the extractors observed, and it says "not established" rather than reaching for
a plausible-sounding guess.

If an Anthropic API key is available and ``--llm`` is passed, the same facts
are handed to Claude to rewrite more fluently. The model is given the fact
sheet and nothing else, and is told not to add anything to it; if the call
fails for any reason the deterministic text stands.
"""

from __future__ import annotations

import json
import logging
from datetime import date

from .config import Config
from .extract.commerce import MODEL_LABELS, MODEL_PHRASES
from .models import CompanyBrief

log = logging.getLogger("dealscope.narrate")

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

SYSTEM_PROMPT = (
    "You write short, plain, sceptical company briefs for someone considering "
    "buying a small business. You are given a fact sheet assembled from the "
    "company's public website.\n\n"
    "Rules:\n"
    "- Use ONLY facts from the sheet. Never add industry context, estimates, "
    "revenue figures, or anything not present.\n"
    "- If something is marked unknown, either say it is unknown or leave it out.\n"
    "- No hype, no marketing voice, no adjectives the sheet does not support.\n"
    "- 120-180 words, 3-4 short paragraphs, plain prose. No headings, no bullets.\n"
    "- Write for a buyer: what the business appears to be, how it appears to make "
    "money, what its size and activity look like, and what the reader should be "
    "most careful about.\n"
    "- Never state or imply financial performance. The sheet contains none."
)


def _humanize(items: list[str], limit: int = 3) -> str:
    kept = [i for i in items if i][:limit]
    if not kept:
        return ""
    if len(kept) == 1:
        return kept[0]
    if len(kept) == 2:
        return f"{kept[0]} and {kept[1]}"
    return ", ".join(kept[:-1]) + f", and {kept[-1]}"


def _freshness(brief: CompanyBrief, today: date) -> str:
    when = brief.momentum.last_content_date
    if when is None:
        return ""
    days = (today - when).days
    if days <= 45:
        return "publishing regularly"
    if days <= 180:
        return f"last published about {max(1, days // 30)} months ago"
    if days <= 400:
        return "last published within the past year"
    return f"last published in {when.year}"


def build_headline(brief: CompanyBrief, today: date) -> str:
    bits: list[str] = []
    model = brief.business_model
    if model.primary != "unknown":
        bits.append(MODEL_LABELS[model.primary].split(" (")[0].split(" / ")[0])
    elif brief.industry_tags:
        bits.append(brief.industry_tags[0])

    if model.sales_motion != "unknown":
        # "sales-led sales" reads badly, and for a trade business the accurate
        # description is that everything routes to a phone call or a quote.
        if model.primary == "local_services":
            bits.append("quote-led")
        elif model.sales_motion == "sales-led":
            bits.append("sales-led")          # "sales-led sales" read badly
        else:
            bits.append(f"{model.sales_motion} sales")
    if brief.scale.headcount_estimate:
        bits.append(f"{brief.scale.headcount_estimate} people")
    if brief.momentum.open_roles:
        bits.append(f"{brief.momentum.open_roles} open roles")

    fresh = _freshness(brief, today)
    if fresh:
        bits.append(fresh)

    detail = " · ".join(bits) if bits else "little public detail available"
    return f"{brief.display_name} — {detail}"


def build_deterministic(brief: CompanyBrief, today: date) -> str:
    """A short brief assembled strictly from what was observed."""
    model = brief.business_model
    scale = brief.scale
    momentum = brief.momentum
    paragraphs: list[str] = []

    # --- what it is ---
    opening = f"{brief.display_name} operates at {brief.domain}"
    if brief.industry_tags:
        opening += f", presenting itself in {_humanize(brief.industry_tags, 2).lower()}"
    opening += "."
    if brief.tagline:
        opening += f" The site leads with “{brief.tagline}”."
    elif brief.description:
        summary = brief.description[:220].rstrip()
        opening += f" It describes itself as: “{summary}”."
    if scale.founded_year:
        opening += f" It claims to have been founded in {scale.founded_year}."
    paragraphs.append(opening)

    # --- how it makes money ---
    # One decision, not two. Independent branches here are what produced
    # "no pricing was found" immediately followed by a list of prices.
    if model.primary != "unknown":
        money = f"Revenue appears to come from {MODEL_PHRASES[model.primary]}"
        if model.confidence:
            money += f" (confidence {int(model.confidence * 100)}% on public signals)"
        money += "."
    elif model.price_points:
        money = (
            "The site publishes prices, but not enough about what is sold or how it "
            "is delivered to establish the revenue model."
        )
    else:
        money = (
            "How the business charges could not be established from the public site — "
            "no pricing, plans, or checkout flow were found."
        )
    if model.price_points:
        money += f" Published prices include {_humanize(model.price_points, 3)}."
        if model.plan_names:
            money += f" Plans are named {_humanize(model.plan_names, 4)}."
    if model.sales_motion != "unknown":
        local = model.primary == "local_services"
        motion = {
            "self-serve": "buyers can sign up without talking to anyone",
            "sales-led": (
                "the site is built around getting people to call or request a quote"
                if local
                else "buying starts with a demo or a sales conversation"
            ),
            "hybrid": "there is both a self-serve path and a sales-led one",
        }.get(model.sales_motion, "")
        if motion:
            money += f" On the evidence of its calls to action, {motion}."
    if model.has_free_tier:
        money += " A free tier or free trial is advertised."
    paragraphs.append(money)

    # --- size and activity ---
    shape: list[str] = []
    if scale.headcount_estimate:
        shape.append(f"headcount looks like {scale.headcount_estimate} ({scale.headcount_basis})")
    if scale.leadership:
        names = _humanize([f"{p['name']} ({p['title']})" for p in scale.leadership], 2)
        shape.append(f"leadership is named publicly — {names}")
    elif not scale.named_people:
        shape.append("nobody is named publicly on the site")
    if scale.named_customers:
        shape.append(f"customers named on the site include {_humanize(scale.named_customers, 3)}")
    if scale.customer_count_claim:
        shape.append(f"the site claims “{scale.customer_count_claim}”")
    if scale.locations:
        shape.append(f"it lists a presence in {_humanize(scale.locations, 2)}")
    if scale.service_areas:
        shape.append(f"it advertises serving {_humanize(scale.service_areas, 2)}")
    if brief.trust.opening_hours:
        shape.append(f"published hours are {brief.trust.opening_hours}")

    activity: list[str] = []
    if momentum.open_roles:
        departments = (
            f" across {_humanize(momentum.hiring_departments, 3)}"
            if momentum.hiring_departments
            else ""
        )
        activity.append(f"{momentum.open_roles} open role(s) are advertised{departments}")
    elif momentum.open_roles == 0:
        activity.append("the careers page is live but lists no open roles")
    fresh = _freshness(brief, today)
    if fresh:
        activity.append(f"the blog is {fresh}" if "publishing" in fresh else f"the blog was {fresh}")
    elif brief.scores is not None and not brief.scores.momentum.assessable:
        activity.append(
            "there is no blog or careers page, which is normal for this kind of "
            "business and says nothing about how it is trading"
        )
    if momentum.funding_mentions:
        activity.append(f"the site mentions {momentum.funding_mentions[0]}")
    if momentum.ownership_notes:
        activity.append(f"it describes itself as {momentum.ownership_notes[0]}")

    combined = shape + activity
    if combined:
        sentence = combined[0][0].upper() + combined[0][1:]
        rest = "; ".join(combined[1:])
        paragraphs.append(sentence + ("; " + rest + "." if rest else "."))

    # --- what to be careful about ---
    caution: list[str] = []
    top_risks = [flag for flag in brief.risk_flags if flag.severity in ("high", "medium")][:2]
    if top_risks:
        caution.append(
            "Worth attention before anything else: "
            + _humanize([flag.title.lower() for flag in top_risks], 2)
            + "."
        )
    if brief.operations.platform_dependencies:
        caution.append(
            f"The site runs on {_humanize(brief.operations.platform_dependencies, 2)}, "
            "so account and asset transfer needs checking."
        )
    coverage = brief.scores.evidence_coverage if brief.scores else None
    if coverage is not None:
        if coverage.value < 40:
            caution.append(
                f"Evidence coverage for this brief is low ({coverage.value:.0f}/100) — "
                "treat everything above as provisional."
            )
        elif coverage.value < 70:
            caution.append(
                f"Evidence coverage is moderate ({coverage.value:.0f}/100); several "
                "standard pages were not found."
            )
    caution.append(
        "Nothing here speaks to revenue, margins, churn, or owner dependency — "
        "none of that is publicly observable."
    )
    paragraphs.append(" ".join(caution))

    return "\n\n".join(p for p in paragraphs if p)


# --- optional LLM rewrite --------------------------------------------------


def build_fact_sheet(brief: CompanyBrief, today: date) -> str:
    """Compact, explicit facts handed to the model. Unknowns are stated as unknown."""
    model = brief.business_model
    facts: dict[str, object] = {
        "domain": brief.domain,
        "name": brief.display_name,
        "tagline": brief.tagline or "unknown",
        "self_description": brief.description[:400] or "unknown",
        "apparent_sector": brief.industry_tags or "unknown",
        "founded_year": brief.scale.founded_year or "unknown",
        "revenue_model": MODEL_LABELS[model.primary],
        "revenue_model_confidence": model.confidence,
        "sales_motion": model.sales_motion,
        "published_prices": model.price_points or "none found",
        "plan_names": model.plan_names or "none found",
        "free_tier_advertised": model.has_free_tier,
        "headcount_estimate": brief.scale.headcount_estimate or "unknown",
        "headcount_basis": brief.scale.headcount_basis or "unknown",
        "named_leadership": [f"{p['name']} — {p['title']}" for p in brief.scale.leadership] or "none found",
        "named_customers": brief.scale.named_customers or "none found",
        "customer_count_claim": brief.scale.customer_count_claim or "none found",
        "locations": brief.scale.locations or "unknown",
        "open_roles": brief.momentum.open_roles if brief.momentum.open_roles is not None else "unknown",
        "hiring_departments": brief.momentum.hiring_departments or "unknown",
        "last_content_date": (
            brief.momentum.last_content_date.isoformat()
            if brief.momentum.last_content_date
            else "no dated content found"
        ),
        "posts_per_month": brief.momentum.posts_per_month if brief.momentum.posts_per_month is not None else "unknown",
        "footer_copyright_year": brief.momentum.copyright_year or "unknown",
        "funding_mentions": brief.momentum.funding_mentions or "none found",
        "platform_dependencies": brief.operations.platform_dependencies or "none detected",
        "notable_tech": [t.name for t in brief.operations.tech][:12] or "none detected",
        "compliance_claims": brief.trust.compliance_claims or "none found",
        "legal_pages_found": list(brief.trust.legal_pages) or "none found",
        "contact_channels": {
            "emails": brief.trust.emails or "none found",
            "phones": brief.trust.phones or "none found",
            "addresses": brief.trust.addresses or "none found",
        },
        "risk_flags": [f"{f.severity}: {f.title} — {f.detail}" for f in brief.risk_flags] or "none",
        # Sent with assessable and rationale: a bare 60 for a plumber's
        # momentum invites the model to write "momentum scores 60" about a
        # measure the code itself declares meaningless.
        "scores": (
            {
                label.lower().replace(" ", "_"): (
                    {"value": score.value, "band": score.band,
                     "why": "; ".join(score.rationale)}
                    if score.assessable
                    else {"value": "not measurable for this business",
                          "why": "; ".join(score.rationale)}
                )
                for label, score in brief.scores.as_pairs()
            }
            if brief.scores
            else "unknown"
        ),
        "pages_read": [p["url"] for p in brief.pages if not p.get("error")],
        "note": (
            "No financial information is available. Revenue, profit, churn, and owner "
            "dependency are all unknown and must not be stated or implied."
        ),
    }
    return json.dumps(facts, indent=2, default=str)


def llm_rewrite(brief: CompanyBrief, config: Config, today: date) -> str | None:
    """Ask Claude to rewrite the brief from the fact sheet. ``None`` on any failure."""
    api_key = config.resolved_api_key()
    if not api_key:
        return None

    try:
        import requests
    except ImportError:  # pragma: no cover
        return None

    payload = {
        "model": config.llm_model,
        "max_tokens": 700,
        "system": SYSTEM_PROMPT,
        "messages": [
            {
                "role": "user",
                "content": (
                    "Write the buyer brief for this company using only these facts.\n\n"
                    + build_fact_sheet(brief, today)
                ),
            }
        ],
    }

    try:
        response = requests.post(
            ANTHROPIC_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
            timeout=60,
        )
        if response.status_code != 200:
            log.warning("LLM rewrite failed: HTTP %s %s", response.status_code, response.text[:200])
            return None
        blocks = response.json().get("content", [])
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
        return text or None
    except Exception as exc:  # network, JSON, schema — all fall back to deterministic
        log.warning("LLM rewrite failed: %s", exc)
        return None


def narrate(brief: CompanyBrief, config: Config, today: date) -> CompanyBrief:
    """Fill in ``headline`` and ``narrative`` on the brief, in place."""
    brief.headline = build_headline(brief, today)
    brief.narrative = build_deterministic(brief, today)
    brief.narrative_source = "deterministic"

    if config.use_llm:
        rewritten = llm_rewrite(brief, config, today)
        if rewritten:
            brief.narrative = rewritten
            brief.narrative_source = f"claude ({config.llm_model})"
        else:
            brief.fetch_notes.append(
                "LLM rewrite unavailable or failed; using the deterministic summary."
            )

    return brief
