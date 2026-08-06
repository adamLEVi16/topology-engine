"""Fixtures for dealscope tests.

Everything here runs offline. Two synthetic sites — a SaaS product and a
Shopify-style shop — stand in for the real web so the suite is deterministic.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from dealscope.fetch import html_to_text, page_title
from dealscope.models import Page

TODAY = datetime.now(timezone.utc).date()
RECENT = (TODAY - timedelta(days=9)).isoformat()
OLDER = (TODAY - timedelta(days=44)).isoformat()
OLDEST = (TODAY - timedelta(days=95)).isoformat()


def make_page(url: str, role: str, html: str, status: int = 200, headers: dict | None = None) -> Page:
    return Page(
        url=url,
        final_url=url,
        status=status,
        role=role,
        html=html,
        text=html_to_text(html),
        title=page_title(html),
        headers=headers or {},
        fetched_at=datetime.now(timezone.utc),
    )


NAV = """
<nav>
  <a href="/pricing">Pricing</a>
  <a href="/about">About</a>
  <a href="/team">Team</a>
  <a href="/careers">Careers</a>
  <a href="/contact">Contact</a>
  <a href="/blog">Blog</a>
  <a href="/customers">Customers</a>
  <a href="/privacy">Privacy Policy</a>
  <a href="/terms">Terms of Service</a>
</nav>
"""

SAAS_HOME = f"""<!doctype html><html><head>
<title>Kettlewind | Scheduling software for clinics</title>
<meta name="description" content="Kettlewind is scheduling and billing software used by independent physiotherapy clinics across the UK.">
<meta property="og:site_name" content="Kettlewind">
<script type="application/ld+json">
{{"@context":"https://schema.org","@type":"Organization","name":"Kettlewind",
  "foundingDate":"2016-04-01","url":"https://kettlewind.test/",
  "address":{{"@type":"PostalAddress","streetAddress":"14 Mill Lane",
    "addressLocality":"Bristol","addressCountry":"United Kingdom"}}}}
</script>
</head><body>
{NAV}
<h1>Scheduling that clinics actually stick with</h1>
<p>Start your 14-day free trial. No credit card required. Cancel anytime.</p>
<p>Trusted by 1,200 clinics across the UK.</p>
<p>Integrates with Xero, Stripe and Mailchimp.</p>
<img src="/l1.svg" alt="Riverside Physio logo">
<img src="/l2.svg" alt="Northgate Clinic logo">
<img src="/l3.svg" alt="Kettlewind logo">
<script src="https://js.stripe.com/v3/"></script>
<script src="https://cdn.segment.com/analytics.js"></script>
<footer><p>&copy; {TODAY.year} Kettlewind Ltd. All rights reserved.</p>
<a href="https://www.linkedin.com/company/kettlewind">LinkedIn</a>
<a href="https://github.com/kettlewind">GitHub</a></footer>
</body></html>"""

SAAS_PRICING = """<!doctype html><html><head><title>Pricing | Kettlewind</title></head><body>
<h1>Pricing</h1>
<div><h3>Starter</h3><p>£29 per month</p><p>Up to 3 practitioners</p></div>
<div><h3>Practice</h3><p>£79 per month</p><p>Up to 12 practitioners</p></div>
<div><h3>Enterprise</h3><p>£249 per month</p><p>Unlimited practitioners</p></div>
<p>All plans billed monthly. 14-day free trial on every tier.</p>
</body></html>"""

SAAS_ABOUT = """<!doctype html><html><head><title>About | Kettlewind</title></head><body>
<h1>About Kettlewind</h1>
<p>Priya Raman founded Kettlewind in 2016 after a decade managing clinic operations.</p>
<p>In 2019, Tomas Eriksen joined to lead engineering.</p>
<p>Today we are a team of 18, based in Bristol.</p>
<p>We are bootstrapped and profitable, with no outside investors.</p>
<p>Kettlewind is SOC 2 Type II certified and GDPR compliant.</p>
</body></html>"""

SAAS_TEAM = """<!doctype html><html><head><title>Team | Kettlewind</title></head><body>
<h1>Our team</h1>
<ul>
  <li><h3>Priya Raman</h3><p>Chief Executive Officer</p></li>
  <li><h3>Tomas Eriksen</h3><p>Head of Engineering</p></li>
  <li><h3>Dana Whitfield</h3><p>Customer Success Manager</p></li>
</ul>
<p>Privacy Policy</p>
</body></html>"""

SAAS_CAREERS = """<!doctype html><html><head><title>Careers | Kettlewind</title></head><body>
<h1>Open roles</h1>
<a href="/careers/senior-backend-engineer">Senior Backend Engineer</a>
<a href="/careers/account-executive">Account Executive</a>
<a href="/careers/product-designer">Product Designer</a>
</body></html>"""

SAAS_CONTACT = """<!doctype html><html><head><title>Contact | Kettlewind</title></head><body>
<h1>Contact us</h1>
<p><a href="mailto:hello@kettlewind.test">hello@kettlewind.test</a></p>
<p><a href="tel:+441179460123">+44 117 946 0123</a></p>
<p>14 Mill Lane, Bristol, BS1 4RN</p>
</body></html>"""

SAAS_BLOG = f"""<!doctype html><html><head><title>Blog | Kettlewind</title></head><body>
<h1>Blog</h1>
<article><h2>Reducing no-shows</h2><time datetime="{RECENT}">recent</time></article>
<article><h2>New billing exports</h2><time datetime="{OLDER}">older</time></article>
<article><h2>Our 2025 roadmap</h2><time datetime="{OLDEST}">oldest</time></article>
</body></html>"""

SAAS_PRIVACY = """<!doctype html><html><head><title>Privacy Policy | Kettlewind</title></head>
<body><h1>Privacy Policy</h1><p>We process personal data under GDPR.</p></body></html>"""

SAAS_TERMS = """<!doctype html><html><head><title>Terms of Service | Kettlewind</title></head>
<body><h1>Terms of Service</h1><p>These terms govern your use of the service.</p></body></html>"""

SAAS_CUSTOMERS = """<!doctype html><html><head><title>Customers | Kettlewind</title></head><body>
<h1>Customers</h1>
<img src="/a.svg" alt="Riverside Physio">
<img src="/b.svg" alt="Northgate Clinic">
<img src="/c.svg" alt="Harbour Sports Medicine">
</body></html>"""

SHOP_HOME = """<!doctype html><html><head>
<title>Bramble &amp; Oak — handmade leather bags</title>
<meta property="og:site_name" content="Bramble &amp; Oak">
<meta name="description" content="Handmade leather bags, cut and stitched in Leeds.">
</head><body>
<nav><a href="/pages/about">Our story</a><a href="/collections/all">Shop all</a></nav>
<h1>Bags built to outlast you</h1>
<p>Free shipping on orders over £80. Add to cart and checkout in seconds.</p>
<p>£145.00</p><p>£210.00</p>
<p>In stock. Returns policy: 30 days.</p>
<script src="https://cdn.shopify.com/s/files/theme.js"></script>
<footer>&copy; 2021 Bramble &amp; Oak</footer>
</body></html>"""


@pytest.fixture
def saas_pages() -> list[Page]:
    return [
        make_page("https://kettlewind.test/", "home", SAAS_HOME, headers={"server": "nginx"}),
        make_page("https://kettlewind.test/pricing", "pricing", SAAS_PRICING),
        make_page("https://kettlewind.test/about", "about", SAAS_ABOUT),
        make_page("https://kettlewind.test/team", "team", SAAS_TEAM),
        make_page("https://kettlewind.test/careers", "careers", SAAS_CAREERS),
        make_page("https://kettlewind.test/contact", "contact", SAAS_CONTACT),
        make_page("https://kettlewind.test/blog", "blog", SAAS_BLOG),
        make_page("https://kettlewind.test/customers", "customers", SAAS_CUSTOMERS),
        make_page("https://kettlewind.test/privacy", "legal", SAAS_PRIVACY),
        make_page("https://kettlewind.test/terms", "legal", SAAS_TERMS),
    ]


@pytest.fixture
def shop_pages() -> list[Page]:
    return [make_page("https://brambleoak.test/", "home", SHOP_HOME)]


@pytest.fixture
def saas_site() -> dict[str, str]:
    """URL -> HTML, for the fake fetcher used in the end-to-end test."""
    return {
        "https://kettlewind.test/": SAAS_HOME,
        "https://kettlewind.test/pricing": SAAS_PRICING,
        "https://kettlewind.test/about": SAAS_ABOUT,
        "https://kettlewind.test/team": SAAS_TEAM,
        "https://kettlewind.test/careers": SAAS_CAREERS,
        "https://kettlewind.test/contact": SAAS_CONTACT,
        "https://kettlewind.test/blog": SAAS_BLOG,
        "https://kettlewind.test/customers": SAAS_CUSTOMERS,
        "https://kettlewind.test/privacy": SAAS_PRIVACY,
        "https://kettlewind.test/terms": SAAS_TERMS,
    }
