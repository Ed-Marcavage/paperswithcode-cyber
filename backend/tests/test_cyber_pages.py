from datetime import date
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.config import Settings, get_settings
from backend.database.connection import get_database_session
from backend.main import create_app
from backend.models.papers import Paper
from backend.services import cyber_page_service as pages
from backend.services import discovery_catalog, trending_posts
from backend.services.paper_service import PaperService
from backend.services.spa_shell_service import reset_cache
from backend.utils.exceptions import PaperNotFoundError

ORIGIN = "https://paperswithcode-cyber.com"
PAPER = Paper(
    id="42",
    arxiv_id="2610.34435",
    source="arxiv",
    title="Security agents & harnesses",
    abstract="A complete abstract about reproducible security research.",
    authors=["A. Researcher"],
    published=date(2026, 10, 30),
    url_abs="https://arxiv.org/abs/2610.34435",
)
ROWS = [
    {
        "paper_id": str(n),
        "reference": str(n),
        "title": f"Security paper {n}",
        "facets": {"year": ["2026"], "contribution": ["harness"]},
    }
    for n in range(51)
]

BLOCK = {
    "heading": "Editor's picks",
    "results": [
        {"reference": "2115", "title": "ARTEX and Beyond: AI-Enabled Penetration Testing Platforms",
         "date_published": "2026-11-13", "publisher": "Cisco Talos",
         "post": {"curated_title": "ARTEX and Beyond, AI-Enabled Penetration Testing Platforms", "curated_pin": 1}},
        {"reference": "2114", "title": "Threat actors running ARTEX agents", "date_published": "2026-11-13",
         "publisher": "AWS", "post": {"curated_pin": 2}},
        {"reference": "2116", "title": "Cyber Chaos Monkey", "date_published": "2026-11-12",
         "publisher": "Shopify", "post": {"curated_pin": 3}},
    ],
}

FEED = [
    {"reference": "301", "title": "Agent harness for code audit", "date_published": "2026-11-10",
     "publisher": "Endor Labs", "post": {"agent_relevance": 4}},
    {"reference": "302", "title": "Raw title", "date_published": "2026-11-09",
     "publisher": "Wiz", "post": {"curated_title": "Evaluating security agents", "agent_relevance": 3, "curated_pin": 5}},
]



@pytest.fixture
def client(monkeypatch, tmp_path):
    settings = get_settings()
    monkeypatch.setattr(settings, "discovery_catalog", True)
    monkeypatch.setattr(settings, "public_site_url", "")
    monkeypatch.setattr(settings, "environment", "development")
    shell = Path(__file__).resolve().parents[2] / "frontend/index.html"
    (tmp_path / "index.html").write_text(shell.read_text())
    monkeypatch.setattr(settings, "frontend_dist_dir", str(tmp_path))
    reset_cache()
    monkeypatch.setattr(
        PaperService, "get_papers", lambda *a, **kw: SimpleNamespace(results=[PAPER])
    )

    def paper(self, reference, **kwargs):
        if reference not in {"42", "2610.34435"}:
            raise PaperNotFoundError(reference)
        return PAPER

    monkeypatch.setattr(PaperService, "get_paper_by_id_or_arxiv", paper)
    monkeypatch.setattr(
        discovery_catalog,
        "terms",
        lambda db: {"contribution": {"harness": "Agent harness"}},
    )
    monkeypatch.setattr(
        discovery_catalog,
        "browse",
        lambda db, filters, limit, offset, include_facet_counts=False, **post_filters: {
            "total": len(ROWS),
            "results": ROWS[offset : offset + limit],
        },
    )
    monkeypatch.setattr(trending_posts, "industry_block", lambda db: BLOCK)
    monkeypatch.setattr(
        trending_posts, "posts_feed",
        lambda db, page, page_size, start_date=None, end_date=None: (FEED, len(FEED)),
    )
    monkeypatch.setattr(pages, "catalog_count", lambda db: len(ROWS))
    monkeypatch.setattr(pages, "sitemap_papers", lambda db, page: ROWS)
    app = create_app()
    app.dependency_overrides[get_database_session] = lambda: object()
    yield TestClient(app)
    reset_cache()


@pytest.mark.parametrize(
    "path,canonical",
    [
        ("/", "/"),
        ("/catalog", "/catalog"),
        ("/catalog?offset=25", "/catalog?offset=25"),
        ("/paper/2610.34435", "/paper/2610.34435"),
    ],
)
def test_initial_html_is_visible_and_has_cyber_metadata(client, path, canonical):
    response = client.get(path, headers={"Host": "spoof.example"})
    assert response.status_code == 200
    html = BeautifulSoup(response.text, "html.parser")
    main = html.select_one("#root main")
    assert main and not main.has_attr("hidden")
    assert "display: none !important" not in response.text
    assert main.find("h1") and main.find("a")
    assert "Cyber" in html.title.text
    assert html.select_one('link[rel="canonical"]')["href"] == ORIGIN + canonical
    assert html.select_one('meta[property="og:url"]')["content"] == ORIGIN + canonical
    assert "https://paperswithcode.co" not in response.text
    assert "spoof.example" not in response.text
    assert "Accept" in response.headers["vary"]
    assert "public" in response.headers["cache-control"]
    assert client.head(path).content == b""
    assert client.head(path).headers["content-type"] == response.headers["content-type"]


@pytest.mark.parametrize(
    "path,alias",
    [
        ("/", "/index.md"),
        ("/catalog?offset=25", "/catalog.md?offset=25"),
        ("/paper/2610.34435", "/paper/2610.34435.md"),
    ],
)
def test_markdown_alternatives_match_negotiation_and_html(client, path, alias):
    html = BeautifulSoup(client.get(path).text, "html.parser")
    assert (
        html.select_one('link[rel="alternate"][type="text/markdown"]')["href"]
        == ORIGIN + alias
    )
    negotiated = client.get(path, headers={"Accept": "text/markdown"})
    forced = client.get(alias, headers={"Accept": "text/html"})
    assert negotiated.status_code == forced.status_code == 200
    assert negotiated.text == forced.text
    assert forced.headers["content-type"].startswith("text/markdown")
    assert forced.headers["link"] == f'<{ORIGIN}{path}>; rel="canonical"'
    assert "Accept" in forced.headers["vary"]
    assert "https://paperswithcode.co" not in forced.text
    assert html.h1.text.replace("<", "\\<").replace(">", "\\>") in forced.text
    assert client.head(alias).content == b""
    assert (
        client.get(path, headers={"Accept": "text/html, text/markdown;q=0.2"})
        .headers["content-type"]
        .startswith("text/html")
    )


def test_catalog_pagination_filters_and_tracking(client):
    html = BeautifulSoup(client.get("/catalog?offset=25").text, "html.parser")
    assert html.find("a", string="Previous")["href"] == "/catalog"
    assert html.find("a", string="Next")["href"] == "/catalog?offset=50"
    assert "Security paper 25" in html.text and "Security paper 0" not in html.text
    assert html.select_one('meta[name="robots"]')["content"] == "index,follow"
    filtered = client.get("/catalog?contribution=harness&utm_source=github")
    html = BeautifulSoup(filtered.text, "html.parser")
    assert (
        html.select_one('link[rel="canonical"]')["href"]
        == ORIGIN + "/catalog?contribution=harness"
    )
    assert filtered.headers["x-robots-tag"] == "noindex,follow"
    assert "Agent harness" in html.text
    assert "contribution=harness" in html.find("a", string="Next")["href"]


@pytest.mark.parametrize(
    "path",
    [
        "/.well-known/openid-configuration",
        "/.well-known/api-catalog",
        "/does-not-exist",
        "/catalog/nope",
        "/robots.txt/nope",
        "/missing.js",
        "/api/nope",
        "/paper/missing",
        "/paper/2999.99999.md",
        "/catalog?offset=-1",
        "/catalog?offset=nope",
        "/catalog?offset=26",
        "/catalog?offset=75",
        "/catalog?contribution=missing",
        "/sitemaps/papers-100.xml",
        "/sitemaps/papers-x.xml",
    ],
)
def test_invalid_urls_are_real_uncached_404s(client, path):
    for method in (client.get, client.head):
        response = method(path)
        assert response.status_code == 404
        assert response.headers["cache-control"] == "no-store"


def test_paper_canonical_redirect_and_jsonld(client):
    for old, target in [
        ("/paper/42.md", "/paper/2610.34435.md"),
        ("/paper/42", "/paper/2610.34435"),
        ("/papers/42", "/paper/2610.34435"),
    ]:
        response = client.get(old, follow_redirects=False)
        assert response.status_code == 301 and response.headers["location"] == target
    html = BeautifulSoup(client.get("/paper/2610.34435").text, "html.parser")
    assert "Security agents & harnesses" in html.h1.text
    assert "reproducible security research" in html.select_one("#root").text
    schema = html.select_one('script[type="application/ld+json"]').string
    assert ORIGIN + "/paper/2610.34435" in schema
    assert ORIGIN + "/catalog" in schema
    assert "/papers/archive" not in schema


def locations(response):
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    return [
        node.text
        for node in ElementTree.fromstring(response.text).iter(
            "{http://www.sitemaps.org/schemas/sitemap/0.9}loc"
        )
    ]


def test_robots_and_sitemap_only_list_canonical_catalog_pages(client):
    robots = client.get("/robots.txt")
    assert robots.headers["content-type"].startswith("text/plain")
    assert f"Sitemap: {ORIGIN}/sitemap.xml\n" in robots.text
    assert locations(client.get("/sitemap.xml")) == [
        ORIGIN + "/sitemaps/static.xml",
        ORIGIN + "/sitemaps/papers-0.xml",
    ]
    assert locations(client.get("/sitemaps/static.xml")) == [
        ORIGIN + p
        for p in ["/", "/catalog", "/catalog?offset=25", "/catalog?offset=50"]
    ]
    assert locations(client.get("/sitemaps/papers-0.xml")) == [
        ORIGIN + "/paper/" + row["reference"] for row in ROWS
    ]
    for path in [
        "/robots.txt",
        "/sitemap.xml",
        "/sitemaps/static.xml",
        "/sitemaps/papers-0.xml",
        "/llms.txt",
    ]:
        assert client.head(path).status_code == 200
        assert client.head(path).content == b""
    assert "/catalog.md" in client.get("/llms.txt").text


def test_canonical_override_staging_and_explicit_shell_path(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "public_site_url", "https://preview.example")
    monkeypatch.setattr(settings, "environment", "staging")
    assert "Disallow: /" in client.get("/robots.txt").text
    for path in [
        "/",
        "/catalog",
        "/catalog.md",
        "/paper/2610.34435",
        "/paper/2610.34435.md",
        "/sitemap.xml",
    ]:
        response = client.get(path)
        assert "noindex" in response.headers["x-robots-tag"]
        assert "https://preview.example" in response.text
    monkeypatch.setattr(settings, "frontend_dist_dir", "/missing-build")
    assert client.get("/").status_code == 503
    assert client.get("/index.md").status_code == 200


@pytest.mark.parametrize(
    "value",
    [
        "http://example.com",
        "https://user:secret@example.com",
        "https://example.com/path",
        "https://example.com?query=1",
        "//example.com",
        "https://example.com\n",
    ],
)
def test_reject_invalid_public_origins(value):
    with pytest.raises(ValidationError):
        Settings(public_site_url=value, _env_file=None)


@pytest.mark.parametrize(
    "path",
    [
        "/mcp",
        "/personal-agents",
        "/developers",
        "/developers/42",
        "/repos/rapid7/metasploit-framework",
        "/orgs/openai",
        "/pdf/2610.34435",
        "/docs/api",
    ],
)
def test_existing_browser_deep_links_remain_available(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert '<div id="root"></div>' in response.text
    assert response.headers["x-robots-tag"] == "noindex,follow"


def test_existing_catalog_api_is_not_intercepted(client):
    response = client.get("/api/v1/catalog/papers?limit=2")
    assert response.status_code == 200
    assert len(response.json()["results"]) == 2


def test_homepage_lists_the_editors_picks_in_html_and_markdown(client):
    html = BeautifulSoup(client.get("/").text, "html.parser")
    section = html.select_one('#root main section[aria-labelledby="highlights-heading"]')
    assert section.h2.text == "Editor's picks"
    links = [(a["href"], a.text) for a in section.select("a")]
    assert links == [("/paper/2115", "ARTEX and Beyond, AI-Enabled Penetration Testing Platforms"),
                     ("/paper/2114", "Threat actors running ARTEX agents"), ("/paper/2116", "Cyber Chaos Monkey")]
    # The block's heading says what it is, so its rows carry no badge.
    assert "Cisco Talos · 2026-11-13" in section.text and "Editor's pick ·" not in section.text
    assert "Editor's picks are three hand-picked industry posts" in html.select_one("#root main header").text
    markdown = client.get("/index.md").text
    assert "## Editor's picks\n" in markdown
    assert f"- [Cyber Chaos Monkey]({ORIGIN}/paper/2116) — Shopify · 2026-11-12" in markdown
    assert markdown.index("## Editor's picks") < markdown.index("## Trending research papers")


def test_homepage_lists_posts_then_papers_for_every_kind(client):
    response = client.get("/")
    html = BeautifulSoup(response.text, "html.parser")
    main = html.select_one("#root main")
    posts = main.select_one('section[aria-labelledby="posts-heading"]')
    papers = main.select_one('section[aria-labelledby="papers-heading"]')
    assert posts.h2.text == "Trending posts about AI agents"
    assert [(a["href"], a.text) for a in posts.select("a")] == [
        ("/paper/301", "Agent harness for code audit"), ("/paper/302", "Evaluating security agents")]
    assert "Endor Labs · 2026-11-10" in posts.text
    # A pinned post after the three picks ranks in the list and keeps the badge.
    assert "Editor's pick · Wiz · 2026-11-09" in posts.text
    assert papers.h2.text == "Trending research papers"
    assert [(a["href"], a.text) for a in papers.select("a")] == [
        ("/paper/2610.34435", "Security agents & harnesses")]
    sections = [section["aria-labelledby"] for section in main.select("section")]
    assert sections == ["highlights-heading", "posts-heading", "papers-heading"]
    header = main.select_one("header").text
    assert "featured posts about AI agents" in header and "GitHub star growth" in header
    assert html.title.text == pages.HOME_TITLE
    assert len(pages.HOME_TITLE) <= 65 and "Security Agent Harnesses" in pages.HOME_TITLE
    assert len(pages.HOME_DESCRIPTION) <= 155
    assert html.select_one('meta[name="description"]')["content"] == pages.HOME_DESCRIPTION
    assert "industry posts, papers, code and benchmarks" in pages.HOME_DESCRIPTION
    assert html.select_one('link[rel="canonical"]')["href"] == ORIGIN + "/"
    assert html.select_one('meta[name="robots"]')["content"] == "index,follow"
    assert response.headers["x-robots-tag"] == "index,follow"

    # ?kind only selects React's tab; the server page and its robots rule are the same.
    for kind in ("paper", "post"):
        variant = client.get(f"/?kind={kind}")
        assert variant.text == response.text
        assert variant.headers["x-robots-tag"] == "index,follow"
        assert client.get(f"/index.md?kind={kind}").text == client.get("/index.md").text

    markdown = client.get("/index.md").text
    assert f"1. [Agent harness for code audit]({ORIGIN}/paper/301) — Endor Labs · 2026-11-10" in markdown
    assert f"2. [Evaluating security agents]({ORIGIN}/paper/302) — Editor's pick · Wiz · 2026-11-09" in markdown
    assert f"1. [Security agents & harnesses]({ORIGIN}/paper/2610.34435)" in markdown
    assert (markdown.index("## Editor's picks") < markdown.index("## Trending posts about AI agents")
            < markdown.index("## Trending research papers"))
    assert "Relevant papers" not in markdown
    assert "featured posts about AI agents" in markdown and "GitHub star growth" in markdown


def test_homepage_keeps_the_trending_papers_query_and_date_window_robots(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        PaperService, "get_papers",
        lambda self, **kw: calls.append(("papers", kw)) or SimpleNamespace(results=[PAPER]),
    )
    monkeypatch.setattr(
        trending_posts, "posts_feed",
        lambda db, page, page_size, start_date=None, end_date=None:
            calls.append(("posts", (page, page_size, start_date, end_date))) or (FEED, len(FEED)),
    )
    client.get("/?kind=paper")
    # The same paper query "/" made before it listed posts.
    assert calls == [("posts", (1, 20, None, None)),
                     ("papers", {"page": 1, "page_size": 20, "order_by": "trending", "latest_only": True})]
    calls.clear()
    window = client.get("/?start_date=2026-11-01&end_date=2026-11-07")
    window_dates = (date(2026, 11, 1), date(2026, 11, 7))
    assert calls == [("posts", (1, 20, *window_dates)),
                     ("papers", {"page": 1, "page_size": 20, "order_by": "trending", "latest_only": True,
                                 "start_date": window_dates[0], "end_date": window_dates[1]})]
    assert window.headers["x-robots-tag"] == "noindex,follow"
    html = BeautifulSoup(window.text, "html.parser")
    assert html.select_one('link[rel="canonical"]')["href"] == ORIGIN + "/"
    assert client.get("/?kind=paper&start_date=2026-11-01").headers["x-robots-tag"] == "noindex,follow"


def test_other_pages_keep_one_relevant_papers_list(client):
    html = BeautifulSoup(client.get("/catalog").text, "html.parser")
    assert html.select_one('#root main section[aria-labelledby="posts-heading"]') is None
    assert "## Trending posts" not in client.get("/catalog.md").text
