"""Technology fingerprinting from public markup and response headers.

Useful to an acquirer in two ways: it hints at how the business operates
(hosted store vs. custom app), and it exposes platform dependencies that
become migration cost or key-man risk after a sale.
"""

from __future__ import annotations

import re

from ..models import ROLE_HOME, ROLE_PRICING, ROLE_PRODUCT, Evidence, Page, TechFinding
from . import structured as st

# name -> (category, pattern matched against page HTML)
HTML_FINGERPRINTS: dict[str, tuple[str, str]] = {
    # Site platforms / CMS
    "WordPress": ("CMS", r"wp-content|wp-includes|/wp-json/"),
    "Shopify": ("E-commerce platform", r"cdn\.shopify\.com|shopify\.theme|myshopify\.com"),
    "Squarespace": ("Site builder", r"squarespace\.com|static1\.squarespace"),
    "Wix": ("Site builder", r"wix\.com|wixstatic\.com|X-Wix"),
    "Webflow": ("Site builder", r"webflow\.(com|io)|data-wf-page"),
    "WooCommerce": ("E-commerce platform", r"woocommerce"),
    "BigCommerce": ("E-commerce platform", r"bigcommerce\.com"),
    "Magento": ("E-commerce platform", r"magento|/static/version\d+/frontend"),
    "Ghost": ("CMS", r"ghost\.io|/ghost/api/"),
    "Drupal": ("CMS", r"drupal|/sites/default/files"),
    "HubSpot CMS": ("CMS", r"hs-sites\.com|hubspot\.net/hub"),
    # Front-end frameworks
    "Next.js": ("Framework", r"/_next/static|__NEXT_DATA__"),
    "Nuxt": ("Framework", r"/_nuxt/|__NUXT__"),
    "React": ("Framework", r"react(-dom)?[.@][\d.]|data-reactroot"),
    "Vue": ("Framework", r"vue[.@][\d.]|data-v-[0-9a-f]{8}"),
    "Angular": ("Framework", r"ng-version|angular[.@][\d.]"),
    "Svelte": ("Framework", r"svelte-[0-9a-z]{6}|/_app/immutable/"),
    "Gatsby": ("Framework", r"___gatsby|gatsby-"),
    "Astro": ("Framework", r"astro-island|data-astro-"),
    # Analytics
    "Google Analytics": ("Analytics", r"googletagmanager\.com/gtag|google-analytics\.com|gtag\("),
    "Google Tag Manager": ("Analytics", r"googletagmanager\.com/gtm\.js|GTM-[A-Z0-9]{4,}"),
    "Plausible": ("Analytics", r"plausible\.io/js"),
    "Fathom": ("Analytics", r"usefathom\.com"),
    "Mixpanel": ("Analytics", r"mixpanel"),
    "Amplitude": ("Analytics", r"amplitude\.com/libs|amplitude\.getInstance"),
    "Segment": ("Analytics", r"cdn\.segment\.(com|io)|analytics\.load\("),
    "Hotjar": ("Analytics", r"hotjar\.com|hjSiteSettings"),
    "PostHog": ("Analytics", r"posthog\.(com|js)"),
    # Marketing / CRM
    "HubSpot": ("Marketing / CRM", r"js\.hs-scripts\.com|hubspot\.com/analytics"),
    "Marketo": ("Marketing / CRM", r"marketo\.(net|com)"),
    "Mailchimp": ("Marketing / CRM", r"mailchimp\.com|list-manage\.com"),
    "Klaviyo": ("Marketing / CRM", r"klaviyo\.com"),
    "Salesforce": ("Marketing / CRM", r"salesforce\.com|force\.com"),
    "Facebook Pixel": ("Advertising", r"connect\.facebook\.net.*fbevents|fbq\("),
    "Google Ads": ("Advertising", r"googleadservices\.com|/pagead/conversion"),
    "LinkedIn Insight": ("Advertising", r"snap\.licdn\.com"),
    # Payments / billing
    "Stripe": ("Payments", r"js\.stripe\.com|checkout\.stripe\.com"),
    "PayPal": ("Payments", r"paypal(objects)?\.com"),
    "Paddle": ("Payments", r"paddle\.com|paddle_button"),
    "Chargebee": ("Payments", r"chargebee\.com"),
    "Recurly": ("Payments", r"recurly\.(com|js)"),
    "Square": ("Payments", r"squareup\.com|squarecdn\.com"),
    # Support / product
    "Intercom": ("Support", r"intercom(cdn|\.io|settings)"),
    "Zendesk": ("Support", r"zendesk\.com|zdassets\.com"),
    "Crisp": ("Support", r"crisp\.chat"),
    "Drift": ("Support", r"js\.driftt\.com|drift\.com"),
    "Front": ("Support", r"frontapp\.com"),
    "Help Scout": ("Support", r"helpscout\.(net|com)|beacon-v2"),
    # Auth / infra visible in markup
    "Auth0": ("Auth", r"auth0\.com"),
    "Okta": ("Auth", r"okta(cdn)?\.com"),
    "Firebase": ("Backend", r"firebaseio\.com|firebaseapp\.com"),
    "Algolia": ("Search", r"algolia(net)?\.(com|net)"),
    "Sentry": ("Monitoring", r"sentry(-cdn)?\.(io|com)|browser\.sentry"),
    "Cloudinary": ("Media", r"cloudinary\.com"),
    "Typeform": ("Forms", r"typeform\.com"),
    "Calendly": ("Scheduling", r"calendly\.com"),
}

# name -> (category, header name, pattern)
HEADER_FINGERPRINTS: tuple[tuple[str, str, str, str], ...] = (
    ("Cloudflare", "Hosting / CDN", "server", r"cloudflare"),
    ("Vercel", "Hosting / CDN", "server", r"vercel"),
    ("Netlify", "Hosting / CDN", "server", r"netlify"),
    ("Fastly", "Hosting / CDN", "x-served-by", r"cache-"),
    ("AWS CloudFront", "Hosting / CDN", "via", r"cloudfront"),
    ("AWS S3", "Hosting / CDN", "server", r"amazons3"),
    ("Nginx", "Web server", "server", r"nginx"),
    ("Apache", "Web server", "server", r"apache"),
    ("Shopify", "E-commerce platform", "powered-by", r"shopify"),
    ("WP Engine", "Hosting / CDN", "x-powered-by", r"wp engine"),
    ("Google Cloud", "Hosting / CDN", "server", r"gse|google frontend"),
)

# Platforms whose loss or migration would be a real project post-acquisition.
DEPENDENCY_PLATFORMS = {
    "Shopify", "WordPress", "Squarespace", "Wix", "Webflow", "WooCommerce",
    "BigCommerce", "Magento", "HubSpot CMS", "Ghost",
}

INTEGRATION_HINT = re.compile(
    r"\bintegrat(es|ion|ions)\s+with\s+([A-Z][\w.+-]*(?:,?\s+(?:and\s+)?[A-Z][\w.+-]*){0,6})",
    re.I,
)


def extract(pages: list[Page]) -> tuple[list[TechFinding], list[str], list[str], list[Evidence]]:
    """Return (tech findings, platform dependencies, integrations, evidence)."""
    targets = st.pages_by_role(pages, ROLE_HOME, ROLE_PRICING, ROLE_PRODUCT) or [
        p for p in pages if p.ok
    ][:3]
    findings: dict[str, TechFinding] = {}

    for page in targets:
        html = page.html
        for name, (category, pattern) in HTML_FINGERPRINTS.items():
            if name in findings:
                continue
            match = re.search(pattern, html, re.I)
            if match:
                findings[name] = TechFinding(
                    name=name,
                    category=category,
                    evidence=[
                        Evidence(
                            "operations.tech",
                            name,
                            page.final_url,
                            "regex",
                            0.75,
                            snippet=f"matched “{match.group(0)[:60]}” in page markup",
                        )
                    ],
                )

        for name, category, header, pattern in HEADER_FINGERPRINTS:
            if name in findings:
                continue
            value = page.headers.get(header, "")
            if value and re.search(pattern, value, re.I):
                findings[name] = TechFinding(
                    name=name,
                    category=category,
                    evidence=[
                        Evidence(
                            "operations.tech",
                            name,
                            page.final_url,
                            "header",
                            0.8,
                            snippet=f"{header}: {value[:60]}",
                        )
                    ],
                )

    dependencies = sorted(name for name in findings if name in DEPENDENCY_PLATFORMS)

    integrations: list[str] = []
    for page in targets:
        for match in INTEGRATION_HINT.finditer(page.text):
            for candidate in re.split(r",|\band\b", match.group(2)):
                candidate = candidate.strip(" .")
                if 2 <= len(candidate) <= 30 and candidate[0].isupper():
                    if candidate not in integrations:
                        integrations.append(candidate)
        if len(integrations) >= 12:
            break

    ordered = sorted(findings.values(), key=lambda t: (t.category, t.name))
    evidence = [ev for finding in ordered for ev in finding.evidence]
    return ordered, dependencies, integrations[:12], evidence
