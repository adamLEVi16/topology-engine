"""The pipeline: domain in, brief out."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Callable

from .config import Config, __version__
from .discovery import MULTI_PAGE_ROLES, extra_candidates, plan_candidates
from .extract import commerce, contact, content, hiring, identity, people, tech
from .discovery import links_from
from .fetch import Fetcher, normalize_domain
from .models import (
    ROLE_HOME,
    BusinessModel,
    CompanyBrief,
    Momentum,
    Operations,
    Page,
    RiskFlag,
    Scale,
    TrustProfile,
)
from .narrate import narrate
from .sources import fmcsa
from .scoring import (
    build_diligence_questions,
    build_risk_flags,
    build_scores,
    build_signals,
    build_unknowns,
)

log = logging.getLogger("dealscope")

ProgressFn = Callable[[str], None]


def _noop(_message: str) -> None:
    pass


# A US address line ends in the state, optionally followed by a ZIP. ZIP+4
# ("43004-1234") is as common on a contact page as the 5-digit form, and the
# state it carries is worth +0.15 to a carrier match, so both are read.
_TRAILING_STATE = re.compile(r"\b([A-Z]{2})\b(?:\s+\d{5}(?:-\d{4})?)?\s*$")


def state_from_address(candidate: str) -> str:
    """The two-letter state at the end of an address line, or ""."""
    found = _TRAILING_STATE.search(candidate.strip())
    return found.group(1) if found else ""


def analyze(
    domain: str,
    config: Config | None = None,
    progress: ProgressFn | None = None,
) -> CompanyBrief:
    """Read a company's public website and build a buyer-oriented brief.

    Raises ``ValueError`` only for a domain that cannot be parsed. Every other
    failure — network, parsing, disk, an extractor tripping over unusual
    markup — comes back as a brief that says what went wrong, because a reader
    who asked for a brief should never receive a traceback.
    """
    config = config or Config()
    host = normalize_domain(domain)  # the one error worth refusing outright

    try:
        return _analyze(domain, config, progress)
    except Exception as exc:  # noqa: BLE001 - deliberate last line of defence
        log.exception("analysis of %s failed", host)
        return _failed_brief(host, f"{type(exc).__name__}: {exc}")


def _failed_brief(host: str, reason: str) -> CompanyBrief:
    """A brief describing its own failure, rather than a crash."""
    brief = CompanyBrief(
        domain=host,
        name=host,
        canonical_url=f"https://{host}/",
        generated_at=datetime.now(timezone.utc),
        version=__version__,
        headline=f"{host} — analysis failed",
    )
    brief.fetch_notes = [reason]
    brief.risk_flags = [
        RiskFlag(
            "analysis_failed",
            "This brief could not be completed",
            "high",
            f"Analysis stopped with an internal error: {reason}. Nothing below "
            "has been verified. This is a fault in the tool, not a finding "
            "about the business.",
        )
    ]
    today = datetime.now(timezone.utc).date()
    brief.scores = build_scores(brief, today)
    brief.unknowns = build_unknowns(brief)
    brief.diligence_questions = build_diligence_questions(brief)
    brief.narrative = (
        f"No brief could be produced for {host}: the analysis failed part-way "
        f"through ({reason}). Everything below is a list of what remains unknown."
    )
    return brief


def _analyze(
    domain: str,
    config: Config,
    progress: ProgressFn | None = None,
) -> CompanyBrief:
    """The pipeline itself. Wrapped by :func:`analyze`, which catches its faults."""
    say = progress or _noop
    host = normalize_domain(domain)
    today = datetime.now(timezone.utc).date()

    brief = CompanyBrief(
        domain=host,
        generated_at=datetime.now(timezone.utc),
        version=__version__,
    )

    fetcher = Fetcher(config)
    try:
        say(f"Fetching {host} …")
        home = fetcher.resolve_home(host)
        pages: list[Page] = [home]

        if not home.ok:
            brief.canonical_url = f"https://{host}/"
            brief.name = host
            brief.pages = [home.summary()]
            brief.fetch_notes = fetcher.notes + [f"homepage unreachable: {home.error}"]
            brief.risk_flags = [
                RiskFlag(
                    "unreachable",
                    "The site could not be read",
                    "high",
                    f"Requesting https://{host}/ returned: {home.error}. Nothing in this "
                    "brief could be verified. Check the domain, or whether the site "
                    "blocks automated readers.",
                )
            ]
            brief.scores = build_scores(brief, today)
            brief.unknowns = build_unknowns(brief)
            brief.diligence_questions = build_diligence_questions(brief)
            brief.headline = f"{host} — site unreachable"
            brief.narrative = (
                f"No brief could be produced for {host}: the homepage did not return "
                "readable HTML. Everything below is a list of what remains unknown."
            )
            return brief

        # A page full of text but nearly free of links means the navigation is
        # assembled by JavaScript. This tool reads server-rendered HTML only, so
        # that has to be said out loud rather than reported as "nothing found".
        home_links = links_from(home, host)
        client_rendered = len(home_links) < 12 and len(home.text.split()) > 400
        if client_rendered:
            fetcher.notes.append(
                f"the homepage exposes only {len(home_links)} server-rendered links, so parts "
                "of this site are likely built client-side and could not be read"
            )

        # Fingerprint the homepage before planning: knowing the site runs on
        # Shopify tells us where its policy pages live.
        home_platforms = tuple(t.name for t in tech.extract([home])[0])

        candidates = plan_candidates(fetcher, home, host, config, home_platforms)

        # If robots.txt asked us to wait a long time between requests, read
        # fewer pages rather than spend ten minutes on one site. Coverage drops,
        # and the brief says why.
        page_delay = fetcher.delay_for(home.final_url or home.url)
        allowance = max(1, config.max_pages - 1)
        if page_delay > config.delay:
            affordable = max(3, int(config.polite_time_budget / page_delay))
            if affordable < allowance:
                allowance = affordable
                fetcher.notes.append(
                    f"page budget reduced to {allowance} to respect the site's "
                    f"requested {page_delay:g}s crawl delay"
                )
        budget = [allowance]
        cursor = {role: 0 for role in candidates}
        accepted = {role: 0 for role in candidates}

        def attempt(role: str) -> bool:
            """Fetch the next untried candidate for ``role``."""
            options = candidates[role]
            index = cursor[role]
            if index >= len(options) or budget[0] <= 0:
                return False

            candidate = options[index]
            cursor[role] = index + 1

            # Sites commonly serve one page under two roles — /our-company as
            # both about and contact. Fetching it twice spends a page of the
            # budget on nothing and double-counts it in "pages read".
            if any(p.url == candidate.url or p.final_url == candidate.url for p in pages):
                return False

            say(f"{role}: {candidate.url}")
            page = fetcher.get(candidate.url, role=role)
            budget[0] -= 1

            if page.ok:
                # A redirect can land on a page already read — /contact often
                # resolves to /our-company. Checking the URL we asked for is
                # not enough; check where we actually arrived.
                landed = page.final_url or page.url
                if any((p.final_url or p.url) == landed for p in pages):
                    fetcher.notes.append(
                        f"{candidate.url} resolves to {landed}, already read as another role"
                    )
                    return False
                pages.append(page)
                accepted[role] += 1
                return True
            if candidate.linked:
                # The site itself published this link and it did not resolve.
                # That is a finding about the site, so it stays in the brief.
                pages.append(page)
            else:
                fetcher.notes.append(f"guessed {candidate.url} → {page.error}")
            return False

        # Breadth first: one shot at every role before spending anything on
        # second guesses. Depth-first here would let a role whose guesses all
        # 404 consume the budget and starve pages that actually exist.
        for role in candidates:
            attempt(role)

        # Roles still empty may be linked from a page we have now read rather
        # than from the homepage. Fold those in ahead of the remaining guesses.
        empty = {role for role in candidates if accepted[role] == 0}
        if empty:
            tried = {c.url for options in candidates.values() for c in options}
            for role, options in extra_candidates(
                [p for p in pages if p.ok], host, empty, tried
            ).items():
                position = cursor[role]
                candidates[role] = (
                    candidates[role][:position] + options + candidates[role][position:]
                )

        # Still short on standard pages? The homepage very likely builds its
        # navigation in the browser. Render it once and re-plan from what that
        # reveals — this is what recovers footers that only exist after JS runs.
        still_empty = {role for role in candidates if accepted[role] == 0}
        renderer = getattr(fetcher, "renderer", None)
        if len(still_empty) >= 3 and renderer is not None and renderer.possible and budget[0] > 0:
            say("Re-reading the homepage with a browser …")
            rendered_home = fetcher.get(
                home.final_url or home.url, role=ROLE_HOME, force_render=True
            )
            budget[0] -= 1
            if rendered_home.ok and rendered_home.rendered:
                pages[0] = home = rendered_home
                client_rendered = True
                recovered = len(links_from(rendered_home, host)) - len(home_links)
                fetcher.notes.append(
                    f"rendered the homepage in a browser and found {max(0, recovered)} "
                    "additional links"
                )
                tried = {c.url for options in candidates.values() for c in options}
                for role, options in extra_candidates(
                    [rendered_home], host, still_empty, tried
                ).items():
                    position = cursor[role]
                    candidates[role] = (
                        candidates[role][:position] + options + candidates[role][position:]
                    )

        # Rescue passes for roles that came back empty.
        for _round in range(3):
            for role in candidates:
                if accepted[role] == 0:
                    attempt(role)

        # Only now spend what is left on second pages where they add something.
        for role in candidates:
            if role in MULTI_PAGE_ROLES and accepted[role] >= 1:
                attempt(role)

        say("Extracting evidence …")

        # Order matters: platform fingerprints and the published contact facts
        # both feed the revenue-model call, and the revenue model in turn seeds
        # the sector description.
        tech_findings, dependencies, integrations, tech_evidence = tech.extract(pages)
        contact_data, contact_evidence = contact.extract(pages, host)

        model, model_evidence = commerce.extract(
            pages,
            platform_hints=[t.name for t in tech_findings],
            contact_facts=contact_data,
        )
        identity_data, identity_evidence = identity.extract(
            pages, host, business_model=model.primary
        )
        people_data, people_evidence = people.extract(
            pages,
            config.max_people,
            config.max_customers,
            company_name=identity_data["name"],
            domain=host,
        )
        hiring_data, hiring_evidence = hiring.extract(pages)
        content_data, content_evidence = content.extract(pages, config.blog_window_days, today)

        # --- assemble ---
        brief.canonical_url = identity_data["canonical_url"]
        brief.name = identity_data["name"]
        brief.tagline = identity_data["tagline"]
        brief.description = identity_data["description"]
        brief.industry_tags = identity_data["industry_tags"]

        brief.business_model = model

        brief.scale = Scale(
            headcount_estimate=people_data["headcount_estimate"],
            headcount_basis=people_data["headcount_basis"],
            named_people=people_data["named_people"],
            leadership=people_data["leadership"],
            locations=contact_data["locations"],
            service_areas=contact_data["service_areas"],
            named_customers=people_data["named_customers"],
            customer_count_claim=people_data["customer_count_claim"],
            founded_year=identity_data["founded_year"],
            evidence=identity_evidence + people_evidence,
        )

        brief.momentum = Momentum(
            open_roles=hiring_data["open_roles"],
            hiring_departments=hiring_data["hiring_departments"],
            role_titles=hiring_data["role_titles"],
            last_content_date=content_data["last_content_date"],
            posts_per_month=content_data["posts_per_month"],
            content_window_days=content_data["content_window_days"],
            funding_mentions=content_data["funding_mentions"],
            ownership_notes=content_data["ownership_notes"],
            copyright_year=content_data["copyright_year"],
            evidence=hiring_evidence + content_evidence,
        )

        brief.operations = Operations(
            tech=tech_findings,
            platform_dependencies=dependencies,
            integrations=integrations,
            evidence=tech_evidence,
        )

        brief.trust = TrustProfile(
            legal_pages=contact_data["legal_pages"],
            compliance_claims=contact_data["compliance_claims"],
            emails=contact_data["emails"],
            phones=contact_data["phones"],
            addresses=contact_data["addresses"],
            opening_hours=contact_data["opening_hours"],
            socials=contact_data["socials"],
            evidence=contact_evidence,
        )

        brief.pages = [page.summary() for page in pages]
        brief.fetch_notes = fetcher.notes

        # --- public records ---
        if config.use_fmcsa:
            if config.usdot:
                # A number is an identity. Nothing to match, nothing to get
                # wrong — which is why this is the path for route businesses.
                say(f"Fetching FMCSA record for USDOT {config.usdot} …")
                carrier, why_not = fmcsa.get_snapshot_with_note(fetcher, config.usdot)
            else:
                say("Checking the FMCSA carrier register …")
                state = ""
                for candidate in brief.trust.addresses + brief.scale.locations:
                    state = state_from_address(candidate)
                    if state:
                        break
                carrier, why_not = fmcsa.find_carrier(
                    fetcher, brief.name or host, state=state
                )
            brief.fleet = carrier
            brief.fleet_note = why_not
            if carrier is not None:
                brief.scale.evidence.extend(carrier.evidence)

        say("Scoring …")
        brief.signals = build_signals(brief, today)
        brief.scores = build_scores(brief, today)
        brief.risk_flags = build_risk_flags(
            brief,
            today,
            client_rendered=client_rendered,
            robots_blocked=len(fetcher.robots_blocked),
        )
        brief.unknowns = build_unknowns(brief)
        brief.diligence_questions = build_diligence_questions(brief)

        say("Writing the summary …")
        narrate(brief, config, today)

        return brief
    finally:
        fetcher.close()


def analyze_many(
    domains: list[str],
    config: Config | None = None,
    progress: ProgressFn | None = None,
) -> list[CompanyBrief]:
    briefs: list[CompanyBrief] = []
    for domain in domains:
        try:
            briefs.append(analyze(domain, config=config, progress=progress))
        except ValueError as exc:
            log.warning("skipping %s: %s", domain, exc)
    return briefs
