"""Evidence extraction from fixture pages."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from dealscope.extract import commerce, contact, content, hiring, identity, people, structured


# --- structured metadata ---


def test_json_ld_objects_and_meta(saas_pages):
    home = saas_pages[0]
    objects = structured.json_ld_objects(home.html)
    orgs = structured.of_type(objects, "Organization")
    assert orgs and orgs[0]["name"] == "Kettlewind"

    metas = structured.meta_tags(home.html)
    assert metas["og:site_name"] == "Kettlewind"
    assert "scheduling and billing software" in metas["description"]


def test_json_ld_handles_graph_containers():
    html = """<script type="application/ld+json">
    {"@graph":[{"@type":"Organization","name":"Inner"}]}</script>"""
    found = structured.of_type(structured.json_ld_objects(html), "Organization")
    assert [o["name"] for o in found] == ["Inner"]


# --- identity ---


def test_identity_prefers_structured_data(saas_pages):
    data, evidence = identity.extract(saas_pages, "kettlewind.test")
    assert data["name"] == "Kettlewind"
    assert data["founded_year"] == 2016
    assert data["tagline"] == "Scheduling that clinics actually stick with"
    assert "physiotherapy clinics" in data["description"]
    assert any(e.method == "json-ld" for e in evidence)


def test_identity_falls_back_to_title_brand():
    from .conftest import make_page

    page = make_page(
        "https://widgetry.test/", "home",
        "<html><head><title>Widgetry | Tools for makers</title></head><body><h1>Hi</h1></body></html>",
    )
    data, _ = identity.extract([page], "widgetry.test")
    assert data["name"] == "Widgetry"


# --- commerce ---


def test_commerce_detects_saas_and_prices(saas_pages):
    model, _evidence = commerce.extract(saas_pages, platform_hints=["Stripe"])
    assert model.primary == "saas"
    assert model.confidence > 0.3
    assert model.sales_motion == "self-serve"
    assert model.currency == "GBP"
    assert any("29" in p for p in model.price_points)
    assert {"Starter", "Practice", "Enterprise"} <= set(model.plan_names)


def test_commerce_detects_ecommerce_from_platform(shop_pages):
    model, _ = commerce.extract(shop_pages, platform_hints=["Shopify"])
    assert model.primary == "ecommerce"


def test_commerce_ignores_plan_words_far_from_prices():
    """A nav item reading "Business" is not a pricing tier."""
    from .conftest import make_page

    page = make_page(
        "https://a.test/pricing", "pricing",
        "<body><p>$10</p><p>Starter</p>" + "<p>filler</p>" * 12 + "<p>Company</p></body>",
    )
    model, _ = commerce.extract([page])
    assert "Starter" in model.plan_names
    assert "Company" not in model.plan_names


def test_commerce_ignores_feature_names_beside_prices_in_prose():
    """Basecamp's "Timesheet" sat next to a price inside an FAQ paragraph."""
    from .conftest import make_page

    page = make_page(
        "https://a.test/pricing", "pricing",
        "<body>"
        "<h3>Pro</h3><p>$299/month</p>"
        "<h4>Timesheet</h4>"
        "<p>The Timesheet upgrade is $50/month flat no matter how many people "
        "you have on your account, and it is included on the Pro package.</p>"
        "</body>",
    )
    model, _ = commerce.extract([page])
    assert "Pro" in model.plan_names
    assert "Timesheet" not in model.plan_names


def test_commerce_does_not_invent_tiers_from_shop_promo_lines(shop_pages):
    """"Spend $50 / free Shipping" is a banner, not two pricing tiers."""
    model, _ = commerce.extract(shop_pages, platform_hints=["Shopify"])
    assert model.plan_names == []


def test_industry_tags_lead_with_the_detected_revenue_model():
    """A shoe shop whose copy is full of brand talk must not read as an agency."""
    from .conftest import make_page

    page = make_page(
        "https://boots.test/", "home",
        "<html><head><title>Bootco</title></head><body>"
        "<h1>Boots</h1>"
        "<p>Our brand strategy and marketing shape every campaign. "
        "Marketing, advertising, brand strategy, campaign after campaign.</p>"
        "</body></html>",
    )

    plain, _ = identity.extract([page], "boots.test")
    seeded, _ = identity.extract([page], "boots.test", business_model="ecommerce")

    assert plain["industry_tags"][0] == "Marketing / advertising"
    assert seeded["industry_tags"][0] == "E-commerce / retail"
    # The keyword reading is kept, just demoted below the harder evidence.
    assert "Marketing / advertising" in seeded["industry_tags"]


# --- people ---


def test_people_pairs_names_with_titles(saas_pages):
    data, _ = people.extract(saas_pages, 12, 15, company_name="Kettlewind", domain="kettlewind.test")
    names = {p["name"] for p in data["named_people"]}
    assert {"Priya Raman", "Tomas Eriksen", "Dana Whitfield"} <= names
    assert "Privacy Policy" not in names
    assert any("Priya Raman" == p["name"] for p in data["leadership"])


def test_people_reads_headcount_and_excludes_own_logo(saas_pages):
    data, _ = people.extract(saas_pages, 12, 15, company_name="Kettlewind", domain="kettlewind.test")
    assert data["headcount_estimate"] == "~18"
    assert data["headcount_basis"] == "stated on the site"
    assert "Kettlewind" not in data["named_customers"]
    assert "Riverside Physio" in data["named_customers"]
    assert "1,200 clinics" in data["customer_count_claim"]


def test_people_finds_founders_described_in_prose():
    from .conftest import SAAS_ABOUT, make_page

    page = make_page("https://k.test/about", "about", SAAS_ABOUT)
    data, _ = people.extract([page], 12, 15, company_name="Kettlewind", domain="kettlewind.test")
    found = {p["name"]: p["title"] for p in data["named_people"]}
    assert found.get("Priya Raman") == "Founder"
    assert "Tomas Eriksen" in found


def test_people_ignores_a_lone_image_that_is_not_a_customer_logo():
    """A stray thumbnail alt-tag became a Basecamp "customer" before this."""
    from .conftest import make_page

    page = make_page(
        "https://a.test/", "home",
        "<body><h1>Product tour</h1>"
        "<section><img src='/v.png' alt='Walkthrough'>"
        "<p>Watch how it works.</p></section></body>",
    )
    data, _ = people.extract([page], 12, 15)
    assert data["named_customers"] == []


def test_people_accepts_logos_in_a_wall_or_under_customer_wording():
    from .conftest import make_page

    wall = make_page(
        "https://a.test/", "home",
        "<body><div><img src='1.svg' alt='Riverside Physio'>"
        "<img src='2.svg' alt='Northgate Clinic'>"
        "<img src='3.svg' alt='Harbour Sports'></div></body>",
    )
    labelled = make_page(
        "https://a.test/", "home",
        "<body><section><h2>Trusted by</h2>"
        "<img src='1.svg' alt='Solo Client Ltd'></section></body>",
    )

    from_wall, _ = people.extract([wall], 12, 15)
    from_heading, _ = people.extract([labelled], 12, 15)

    assert "Riverside Physio" in from_wall["named_customers"]
    assert "Solo Client Ltd" in from_heading["named_customers"]


def test_people_rejects_legal_boilerplate_shaped_like_names():
    """Title-cased terms text reads like "Name is the owner" — it must not match."""
    from .conftest import make_page

    page = make_page(
        "https://a.test/about", "about",
        "<body><p>Authorized User is the owner of an exclusive licence. "
        "The Service is the property of the Company.</p></body>",
    )
    data, _ = people.extract([page], 12, 15)
    assert data["named_people"] == []


# --- hiring ---


def test_hiring_counts_postings(saas_pages):
    data, _ = hiring.extract(saas_pages)
    assert data["open_roles"] == 3
    assert {"Engineering", "Sales", "Design"} <= set(data["hiring_departments"])


def test_hiring_reads_an_explicit_zero():
    from .conftest import make_page

    page = make_page(
        "https://a.test/careers", "careers",
        "<body><h1>Careers</h1><p>We have no open positions right now.</p></body>",
    )
    data, _ = hiring.extract([page])
    assert data["open_roles"] == 0


# --- contact ---


def test_contact_collects_channels_and_legal_pages(saas_pages):
    data, _ = contact.extract(saas_pages, "kettlewind.test")
    assert "hello@kettlewind.test" in data["emails"]
    assert data["phones"]
    assert any("Bristol" in a for a in data["addresses"])
    assert "LinkedIn" in data["socials"] and "GitHub" in data["socials"]
    assert len(data["legal_pages"]) == 2
    assert {"SOC 2", "GDPR"} <= set(data["compliance_claims"])


# --- content ---


def test_parse_dates_ignores_future_and_ancient():
    today = date(2026, 6, 1)
    text = "2026-05-20 and Jan 5, 2027 and 3 March 1994 and 2026-06-01"
    found = content.parse_dates(text, today)
    assert date(2026, 5, 20) in found
    assert date(2026, 6, 1) in found
    assert all(d <= today and d.year >= 2000 for d in found)


def test_content_reads_cadence_and_copyright(saas_pages):
    data, _ = content.extract(saas_pages, 365)
    assert data["last_content_date"] is not None
    assert (date.today() - data["last_content_date"]) < timedelta(days=30)
    assert data["posts_per_month"] and data["posts_per_month"] > 0
    assert data["copyright_year"] == date.today().year
    assert any("bootstrapped" in note.lower() for note in data["ownership_notes"])


# --- regressions found in code review ---


def test_headcount_is_not_taken_from_the_middle_of_a_number():
    """"33,776 people" used to yield a headcount of 776."""
    from dealscope.extract.people import HEADCOUNT

    assert HEADCOUNT.search("We answered emails from 33,776 people last year.") is None
    assert HEADCOUNT.search("We are a team of 18.") is not None


def test_a_customer_count_is_not_read_as_staff():
    from dealscope.extract.people import HEADCOUNT

    assert HEADCOUNT.search("Serving 4,500 people in Dayton every week.") is None


def test_nav_links_are_not_counted_as_job_postings():
    """A careers page saying "no openings" must not report roles from its nav."""
    from .conftest import make_page

    page = make_page(
        "https://a.test/careers", "careers",
        "<body><nav><a href='/careers'>Careers</a><a href='/jobs'>Open Jobs</a></nav>"
        "<h1>Careers</h1><p>We have no open positions right now.</p></body>",
    )
    data, _ = hiring.extract([page])
    assert data["open_roles"] == 0
    assert data["role_titles"] == []


def test_real_postings_are_still_counted_alongside_a_nav():
    from .conftest import make_page

    page = make_page(
        "https://a.test/careers", "careers",
        "<body><nav><a href='/careers'>Careers</a></nav><h1>Open roles</h1>"
        "<a href='/careers/senior-backend-engineer'>Senior Backend Engineer</a>"
        "<a href='/careers/account-executive'>Account Executive</a></body>",
    )
    data, _ = hiring.extract([page])
    assert data["open_roles"] == 2
    assert "Careers" not in data["role_titles"]


def test_funding_mentions_come_only_from_the_companys_own_pages():
    """A publication's blog is full of other companies' funding rounds."""
    from .conftest import make_page

    home = make_page("https://pub.test/", "home", "<body><h1>Pub</h1></body>")
    blog = make_page(
        "https://pub.test/blog", "blog",
        "<body><p>Alphabet is raising $80 billion through a package of equity "
        "offerings, and the startup closed a Series B led by Acme Ventures.</p></body>",
    )
    data, _ = content.extract([home, blog], 365)
    assert data["funding_mentions"] == []


def test_a_consultancy_is_never_described_as_self_serve():
    """You cannot buy an agency without talking to anyone."""
    from .conftest import make_page

    page = make_page(
        "https://agency.test/", "home",
        "<body><h1>Consulting</h1><p>Get started today. Sign up for our newsletter. "
        "Our clients include global banks. Our approach is bespoke and tailored to your "
        "engagement. Case studies show our process. Request a proposal.</p></body>",
    )
    model, _ = commerce.extract([page])
    assert model.primary == "services"
    assert model.sales_motion != "self-serve"


def test_leadership_is_ordered_by_seniority_not_alphabetically():
    """The CEO used to be cut from the summary by two colleagues named A and B."""
    from .conftest import make_page

    page = make_page(
        "https://a.test/team", "team",
        "<body><ul>"
        "<li><h3>Anna Miragliuolo</h3><p>Chief People Officer</p></li>"
        "<li><h3>Becky Dunbar</h3><p>Chief Financial Officer</p></li>"
        "<li><h3>Chad Pytel</h3><p>Developer and CEO</p></li>"
        "</ul></body>",
    )
    data, _ = people.extract([page], 12, 15)
    assert data["leadership"][0]["name"] == "Chad Pytel"


def test_placeholder_alt_text_is_not_a_customer():
    from .conftest import make_page

    page = make_page(
        "https://a.test/customers", "customers",
        "<body><h2>Customers</h2><img src='1.svg' alt='Client'>"
        "<img src='2.svg' alt='Real Chemistry'><img src='3.svg' alt='Postmates'></body>",
    )
    data, _ = people.extract([page], 12, 15)
    assert "Client" not in data["named_customers"]
    assert "Real Chemistry" in data["named_customers"]


def test_platform_wide_social_urls_are_rejected():
    """github.com/sponsors belongs to GitHub, not to the company."""
    from .conftest import make_page

    page = make_page(
        "https://a.test/", "home",
        "<body><a href='https://github.com/sponsors'>Sponsor us</a>"
        "<a href='https://linkedin.com/company/acme-inc'>LinkedIn</a></body>",
    )
    data, _ = contact.extract([page], "a.test")
    assert "GitHub" not in data["socials"]
    assert data["socials"].get("LinkedIn", "").endswith("acme-inc")


def test_a_footer_social_link_beats_a_one_off_mention():
    """A real account is in the footer of every page; a stray link appears once."""
    from .conftest import make_page

    footer = "<a href='https://instagram.com/acmeco'>Instagram</a>"
    pages = [
        make_page("https://a.test/", "home", f"<body>{footer}</body>"),
        make_page("https://a.test/about", "about", f"<body>{footer}</body>"),
        make_page(
            "https://a.test/blog", "blog",
            f"<body><a href='https://instagram.com/some_designer'>a designer</a>{footer}</body>",
        ),
    ]
    data, _ = contact.extract(pages, "a.test")
    assert data["socials"]["Instagram"].endswith("acmeco")


# --- second review: mirror assertions beside each fix ---


def test_headcount_reads_thousands_separators_whole():
    """The first fix turned "a team of 1,200" into a headcount of 1."""
    from dealscope.extract.people import HEADCOUNT

    match = HEADCOUNT.search("We are a team of 1,200 people.")
    assert match and "1,200" in match.group(0)


def test_a_sentence_comma_after_the_number_still_matches():
    """"a team of 18, based in Bristol" — the comma is punctuation, not a group."""
    from dealscope.extract.people import HEADCOUNT

    match = HEADCOUNT.search("Today we are a team of 18, based in Bristol.")
    assert match and "18" in match.group(0)


@pytest.mark.parametrize(
    "text,expected",
    [("€29,99", 29.99), ("29,99 €", 29.99), ("49 EUR", 49.0),
     ("$1,200", 1200.0), ("29.99 USD", 29.99)],
)
def test_prices_are_read_under_both_separator_conventions(text, expected):
    """"€29,99" was reported as €29 — a wrong price, stated as published."""
    from dealscope.extract.commerce import PRICE, parse_amount

    match = PRICE.search(text)
    assert match, f"no price found in {text!r}"
    assert parse_amount(match.group("amt") or match.group("amt2")) == expected


def test_a_utf8_page_that_declares_encoding_only_in_markup_is_readable():
    """Latin-1 decoding mangled every accented name and broke the euro sign."""
    from dealscope.fetch import decode_html

    raw = "<html><head><meta charset='utf-8'></head><body>Café — 49 €</body></html>".encode()
    decoded = decode_html(raw, "text/html", "ISO-8859-1")   # header omits charset
    assert "Café" in decoded and "€" in decoded


def test_service_area_headings_are_matched():
    """Local sites write these as title-case headings."""
    from dealscope.extract.contact import SERVICE_AREA

    for text in ("Proudly Serving Dayton and Springfield",
                 "Service Area: Dayton, Springfield",
                 "Areas We Serve: Dayton"):
        assert SERVICE_AREA.search(text), text

    # The captured area, not just the trigger: a heading is only useful if the
    # place name survives it intact.
    assert (
        SERVICE_AREA.search("Proudly Serving Dayton and Springfield since 1994")
        .group("area")
        == "Dayton and Springfield"
    )


def test_service_area_does_not_swallow_lowercase_marketing_copy():
    """The trigger is case-insensitive; the place name is not.

    A pattern-wide re.I would let [A-Z] match anything, so a SaaS homepage
    saying "we serve enterprise teams" would report a service area, add a
    Service area row to the brief, and earn +8 public-footprint points.
    """
    from dealscope.extract.contact import SERVICE_AREA

    for text in (
        "We serve customers in many industries nationwide.",
        "Serving our community for 30 years.",
        "we serve enterprise teams across finance, healthcare and retail.",
    ):
        assert SERVICE_AREA.search(text) is None, text


def test_state_is_read_from_both_zip_forms():
    """The state narrows the FMCSA search; ZIP+4 must not hide it."""
    from dealscope.analyzer import state_from_address

    assert state_from_address("1234 Main St, Columbus, OH 43004") == "OH"
    assert state_from_address("1234 Main St, Columbus, OH 43004-1234") == "OH"
    assert state_from_address("1234 Main St, Columbus, OH") == "OH"


def test_state_is_empty_when_the_line_does_not_end_in_one():
    from dealscope.analyzer import state_from_address

    assert state_from_address("1234 Main Street, Suite 400") == ""
    assert state_from_address("Columbus, Ohio 43004") == ""


def test_a_hostname_merely_ending_in_x_com_is_not_a_profile():
    from dealscope.extract.contact import SOCIAL_PATTERNS
    import re as _re

    pattern = SOCIAL_PATTERNS["X / Twitter"]
    assert _re.search(pattern, "https://www.netflix.com/title/80100172") is None
    assert _re.search(pattern, "https://x.com/thoughtbot")


def test_a_section_index_link_does_not_overrule_no_openings():
    from .conftest import make_page

    page = make_page(
        "https://a.test/careers", "careers",
        "<body><nav><a href='/careers'>Careers</a><a href='/jobs'>Open Jobs</a>"
        "<a href='/careers/engineering'>Engineering</a></nav>"
        "<p>We have no open positions right now.</p></body>",
    )
    data, _ = hiring.extract([page])
    assert data["open_roles"] == 0
