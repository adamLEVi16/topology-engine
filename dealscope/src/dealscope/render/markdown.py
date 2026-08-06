"""Markdown and plain-text rendering of a brief."""

from __future__ import annotations

import re

from ..extract.commerce import MODEL_LABELS
from ..models import CompanyBrief

DISCLAIMER = (
    "This brief is assembled automatically from a company's public website. "
    "It is a starting point for research, not a substitute for financial, legal, "
    "or technical due diligence. Nothing here has been verified against filings, "
    "accounts, or any third-party source."
)

SEVERITY_MARK = {"high": "!!!", "medium": "!!", "low": "!"}


def _row(label: str, value: str) -> str:
    return f"| {label} | {value} |"


def _bullets(items: list[str], empty: str = "_None found._") -> str:
    return "\n".join(f"- {item}" for item in items) if items else empty


def to_markdown(brief: CompanyBrief) -> str:
    out: list[str] = []
    scale, model, momentum, trust = brief.scale, brief.business_model, brief.momentum, brief.trust

    out.append(f"# {brief.headline}")
    out.append("")
    generated = brief.generated_at.strftime("%Y-%m-%d %H:%M UTC") if brief.generated_at else "unknown"
    out.append(
        f"**{brief.display_name}** · [{brief.domain}]({brief.canonical_url}) · "
        f"generated {generated} by dealscope v{brief.version}"
    )
    out.append("")
    out.append(f"> {DISCLAIMER}")
    out.append("")

    # --- summary ---
    out.append("## Summary")
    out.append("")
    out.append(brief.narrative)
    out.append("")
    if brief.narrative_source != "deterministic":
        out.append(f"_Summary prose written by {brief.narrative_source} from the extracted facts._")
        out.append("")

    # --- scorecard ---
    if brief.scores:
        out.append("## Scorecard")
        out.append("")
        out.append("| Measure | Score | Band | Basis |")
        out.append("|---|---:|---|---|")
        for label, score in brief.scores.as_pairs():
            basis = "; ".join(score.rationale) or "—"
            shown = f"{score.value:.0f}/100" if score.assessable else "not measured"
            out.append(f"| {label} | {shown} | {score.band} | {basis} |")
        out.append("")
        out.append(
            "_Scores describe what the public website shows, not the quality of the "
            "business. Evidence coverage is the confidence gauge for this brief._"
        )
        out.append("")

    # --- business model ---
    out.append("## Business model")
    out.append("")
    out.append("| Field | Value |")
    out.append("|---|---|")
    out.append(_row("Revenue model", MODEL_LABELS[model.primary]))
    if model.confidence:
        out.append(_row("Confidence", f"{model.confidence:.0%} (from public signals)"))
    if model.secondary:
        out.append(_row("Secondary signals", ", ".join(MODEL_LABELS[s] for s in model.secondary)))
    out.append(_row("Sales motion", model.sales_motion))
    out.append(_row("Published prices", ", ".join(model.price_points) or "none found"))
    if model.plan_names:
        out.append(_row("Plans / tiers", ", ".join(model.plan_names)))
    if model.billing_periods:
        out.append(_row("Billing periods", ", ".join(model.billing_periods)))
    if model.has_free_tier is not None:
        out.append(_row("Free tier advertised", "yes" if model.has_free_tier else "not found"))
    out.append("")

    # --- scale ---
    out.append("## Scale and team")
    out.append("")
    out.append("| Field | Value |")
    out.append("|---|---|")
    out.append(_row("Headcount signal", scale.headcount_estimate or "not established"))
    if scale.headcount_basis:
        out.append(_row("Basis", scale.headcount_basis))
    out.append(_row("Founded", str(scale.founded_year) if scale.founded_year else "not stated"))
    out.append(_row("Locations", ", ".join(scale.locations) or "not stated"))
    if scale.service_areas:
        out.append(_row("Service area", "; ".join(scale.service_areas)))
    out.append(_row("Named customers", ", ".join(scale.named_customers) or "none found"))
    if scale.customer_count_claim:
        out.append(_row("Customer claim", f"“{scale.customer_count_claim}” (marketing claim)"))
    out.append("")

    if scale.named_people:
        out.append("### People named on the site")
        out.append("")
        for person in scale.named_people:
            title = f" — {person['title']}" if person.get("title") else ""
            out.append(f"- **{person['name']}**{title}")
        out.append("")

    # --- momentum ---
    out.append("## Momentum")
    out.append("")
    out.append("| Field | Value |")
    out.append("|---|---|")
    out.append(
        _row("Open roles", str(momentum.open_roles) if momentum.open_roles is not None else "not established")
    )
    if momentum.hiring_departments:
        out.append(_row("Hiring in", ", ".join(momentum.hiring_departments)))
    out.append(
        _row(
            "Most recent dated content",
            momentum.last_content_date.isoformat() if momentum.last_content_date else "none found",
        )
    )
    if momentum.posts_per_month is not None:
        out.append(_row("Publishing rate", f"~{momentum.posts_per_month}/month"))
    if momentum.copyright_year:
        out.append(_row("Footer copyright", str(momentum.copyright_year)))
    if momentum.funding_mentions:
        out.append(_row("Funding mentions", "; ".join(momentum.funding_mentions)))
    if momentum.ownership_notes:
        out.append(_row("Ownership notes", "; ".join(momentum.ownership_notes)))
    out.append("")
    if momentum.role_titles:
        out.append("### Open roles listed")
        out.append("")
        out.append(_bullets(momentum.role_titles))
        out.append("")

    # --- operations ---
    out.append("## Operations and technology")
    out.append("")
    if brief.operations.tech:
        grouped: dict[str, list[str]] = {}
        for finding in brief.operations.tech:
            grouped.setdefault(finding.category, []).append(finding.name)
        out.append("| Category | Detected |")
        out.append("|---|---|")
        for category in sorted(grouped):
            out.append(_row(category, ", ".join(sorted(grouped[category]))))
        out.append("")
    else:
        out.append("_No technology fingerprints were detected._")
        out.append("")
    if brief.operations.platform_dependencies:
        out.append(
            f"**Platform dependency:** {', '.join(brief.operations.platform_dependencies)}. "
            "Confirm these accounts transfer with the sale."
        )
        out.append("")
    if brief.operations.integrations:
        out.append(f"**Advertised integrations:** {', '.join(brief.operations.integrations)}")
        out.append("")

    # --- trust ---
    out.append("## Contact and trust surface")
    out.append("")
    out.append("| Field | Value |")
    out.append("|---|---|")
    out.append(_row("Emails", ", ".join(trust.emails) or "none found"))
    out.append(_row("Phones", ", ".join(trust.phones) or "none found"))
    out.append(_row("Addresses", "; ".join(trust.addresses) or "none found"))
    if trust.opening_hours:
        out.append(_row("Opening hours", trust.opening_hours))
    out.append(
        _row("Socials", ", ".join(f"[{k}]({v})" for k, v in trust.socials.items()) or "none found")
    )
    out.append(
        _row(
            "Legal pages",
            ", ".join(f"[{k}]({v})" for k, v in trust.legal_pages.items()) or "none found",
        )
    )
    out.append(_row("Compliance claims", ", ".join(trust.compliance_claims) or "none found"))
    out.append("")

    # --- risks ---
    out.append("## Risk flags")
    out.append("")
    if brief.risk_flags:
        for flag in brief.risk_flags:
            mark = SEVERITY_MARK.get(flag.severity, "")
            out.append(f"### {mark} {flag.title} ({flag.severity})")
            out.append("")
            out.append(flag.detail)
            if flag.evidence:
                out.append("")
                for ev in flag.evidence[:3]:
                    out.append(f"  - _{ev.short()}_ — [source]({ev.source_url})")
            out.append("")
    else:
        out.append("_No risk flags were raised by the checks this tool runs._")
        out.append("")

    # --- unknowns ---
    out.append("## What this brief cannot tell you")
    out.append("")
    out.append(_bullets(brief.unknowns))
    out.append("")

    # --- questions ---
    out.append("## Questions to ask the seller")
    out.append("")
    out.append("\n".join(f"{i}. {q}" for i, q in enumerate(brief.diligence_questions, 1)))
    out.append("")

    # --- evidence ---
    evidence = brief.all_evidence()
    if evidence:
        out.append("## Evidence")
        out.append("")
        out.append("Every claim above traces back to one of these observations.")
        out.append("")
        out.append("| Field | Observed | Method | Confidence | Source |")
        out.append("|---|---|---|---:|---|")
        for ev in evidence:
            value = ev.value.replace("|", "\\|")[:90]
            out.append(
                f"| `{ev.field}` | {value} | {ev.method} | {ev.confidence:.2f} | "
                f"[link]({ev.source_url}) |"
            )
        out.append("")

    # --- pages ---
    out.append("## Pages read")
    out.append("")
    out.append("| Role | Status | Words | URL |")
    out.append("|---|---|---:|---|")
    for page in brief.pages:
        status = page.get("error") or page.get("status")
        out.append(f"| {page['role']} | {status} | {page.get('words', 0)} | {page['url']} |")
    out.append("")

    if brief.fetch_notes:
        out.append("### Fetch notes")
        out.append("")
        out.append(_bullets(brief.fetch_notes))
        out.append("")

    return "\n".join(out)


_MD_NOISE = re.compile(r"[*_`>]|^\|.*\|$", re.M)


def to_text(brief: CompanyBrief) -> str:
    """Terminal-friendly rendering: the summary, scores, risks, and questions."""
    lines: list[str] = []
    rule = "─" * 72

    lines.append(rule)
    lines.append(brief.headline)
    lines.append(rule)
    lines.append("")
    lines.append(brief.narrative)
    lines.append("")

    if brief.scores:
        lines.append("SCORES")
        for label, score in brief.scores.as_pairs():
            if not score.assessable:
                lines.append(f"  {label:<18} {'·' * 20}      —  not assessable for this business")
                continue
            bar = "█" * int(score.value / 5) + "·" * (20 - int(score.value / 5))
            lines.append(f"  {label:<18} {bar} {score.value:5.0f}/100  {score.band}")
        lines.append("")

    if brief.risk_flags:
        lines.append("RISK FLAGS")
        for flag in brief.risk_flags:
            lines.append(f"  [{flag.severity.upper():<6}] {flag.title}")
        lines.append("")

    lines.append("CANNOT BE DETERMINED FROM A WEBSITE")
    for item in brief.unknowns[:8]:
        lines.append(f"  · {item}")
    lines.append("")

    lines.append("QUESTIONS TO ASK THE SELLER")
    for index, question in enumerate(brief.diligence_questions[:10], 1):
        lines.append(f"  {index:>2}. {question}")
    lines.append("")

    ok = sum(1 for p in brief.pages if not p.get("error"))
    lines.append(f"Read {ok} of {len(brief.pages)} pages attempted on {brief.domain}.")
    lines.append(DISCLAIMER)
    return "\n".join(lines)
