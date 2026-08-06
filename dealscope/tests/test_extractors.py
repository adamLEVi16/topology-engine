"""Evidence extraction from fixture pages."""

from __future__ import annotations

from datetime import date, timedelta

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
