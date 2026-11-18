"""Cyber page models built from the same read services as the React catalog."""

from datetime import date
from urllib.parse import quote, urlencode

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.services import discovery_catalog, trending_posts
from backend.services.discovery_page_service import (
    DiscoveryLink,
    DiscoveryPage,
    DiscoveryPaperLink,
)
from backend.services.paper_service import PaperService
from backend.utils.urls import get_paper_route_identifier

MCP_GUIDE = """Use find_posts for industry engineering practice, agent harnesses, benchmark findings,
defender reports and vulnerability triage; browse_catalog/search_papers for papers and
repositories; list_developers/get_developer for people; list_organizations/get_organization
for publishers; catalog_filters for the current vocabulary. Each facet accepts one slug,
never an array. Lists have a maximum page size of 25 (find_posts: 10). Posts include
publisher, summary, reviewed agent relevance, type, tier and publication date when known;
all catalog entities include absolute catalog_url links. Relevance 3+ usually suits security
agent builders; use 0 for general vulnerability, malware or threat reporting. Empty narrow
searches do not establish missing coverage: follow the filter-loosening hint.
Work rows use id (pass to get_paper_info/read_paper), published, summary and source_url.
Taxonomy, benchmark, conference and framework tools are inherited and sparse here.
REST reviewed-post search: /api/v1/catalog/posts; reviewed types: /api/v1/catalog/post-types.
The pinned CLI repository is the base server; the website repository owns this Cyber profile.
"""

PAGE_SIZE = 25
SITEMAP_SIZE = 1000
AXES = ("topic", "target", "contribution", "kind", "year")
# Keep aligned with frontend/src/lib/cyberCopy.ts (cyberHomeTitle, cyberHomeDescription).
# "/" lists industry posts and papers, so the description names both. Search results cut
# descriptions after about 155 characters and titles after about 60.
HOME_TITLE = "AI Pentesting & Security Agent Harnesses | Papers With Code Cyber"
HOME_DESCRIPTION = "Explore AI pentesting tools and security agent harnesses: industry posts, papers, code and benchmarks for vulnerability discovery, code audit and fuzzing."
CATALOG_TITLE = "AI Pentesting Tools & Cybersecurity Research"
CATALOG_DESCRIPTION = "Find AI pentesting tools, security agent harnesses, papers and benchmarks. Filter cybersecurity research by topic, target and contribution."
# Keep aligned with frontend/src/lib/cyberCopy.ts (cyberTrendingIndustryNote,
# cyberTrendingPostsDescription, cyberTrendingPapersDescription).
INDUSTRY_NOTE = "Editor's picks are three hand-picked posts and papers; the feed below ranks other industry posts and research papers."
# React's Trending opens with the Editor's picks block, then the feed's switch on posts
# (?kind=paper shows papers); the server page lists the picks, then both feeds, posts
# first, so crawlers keep the paper links. Pinned posts in the posts list are labelled
# like React's "Editor's pick" badge.
POSTS_HEADING = "Trending posts about AI agents"
PAPERS_HEADING = "Trending research papers"
EDITORS_PICK = "Editor's pick"
POSTS_FEED_DESCRIPTION = "Industry posts · featured posts about AI agents, ranked by review scores (technical depth plus originality, plus 1 for agent-harness engineering), halved for every 7 days since publication."
PAPERS_FEED_DESCRIPTION = "Research papers · GitHub star growth, then total stars. Newly tracked repositories start with total-star ordering until enough observations exist. Stars describe the entire repository, not paper quality."


def _post_link(row: dict, badge: bool = False) -> DiscoveryPaperLink:
    """A Trending catalog work as a page link; with ``badge``, a pinned work is marked
    as an editor's pick (feed rows; the picks block has its own heading)."""
    post = row["post"] or {}
    authors = row.get("authors") or []
    publisher = (row.get("publisher") or "") if row["kind"] == "post" else (
        authors[0] + (" et al." if len(authors) > 1 else "") if authors else ""
    )
    label = " · ".join(value for value in (
        EDITORS_PICK if badge and trending_posts.pin(row) is not None else "", publisher) if value)
    return DiscoveryPaperLink(
        quote(row["reference"], safe=""),
        post.get("curated_title") or row["title"],
        date.fromisoformat(row["date_published"]) if row["date_published"] else None,
        label,
    )


def homepage(db: Session, params) -> DiscoveryPage:
    dates = {
        key: date.fromisoformat(params[key])
        for key in ("start_date", "end_date")
        if params.get(key)
    }
    # ?kind only picks React's tab: every kind gets the same page, with both lists.
    posts, _ = trending_posts.posts_feed(
        db, 1, 20, dates.get("start_date"), dates.get("end_date")
    )
    papers = PaperService(db).get_papers(
        page=1, page_size=20, order_by="trending", latest_only=True, **dates
    )
    # The same Editor's picks block React shows above the feed, so the links are crawlable.
    block = trending_posts.industry_block(db)
    highlights = tuple(_post_link(row) for row in block["results"])
    return DiscoveryPage(
        kind="Cybersecurity research",
        canonical_path="/",
        title=HOME_TITLE,
        description=HOME_DESCRIPTION,
        heading="Trending Research",
        body_markdown=HOME_DESCRIPTION
        + " "
        + INDUSTRY_NOTE
        + "\n\n"
        + POSTS_FEED_DESCRIPTION
        + "\n\n"
        + PAPERS_FEED_DESCRIPTION,
        highlight_heading=block["heading"],
        highlight_links=highlights,
        breadcrumbs=(),
        entity_heading="More on this site",
        entity_links=(
            DiscoveryLink("/catalog", "Browse catalog"),
            DiscoveryLink("/mcp", "Connect an agent"),
        ),
        post_heading=POSTS_HEADING,
        post_links=tuple(_post_link(row, badge=True) for row in posts),
        paper_heading=PAPERS_HEADING,
        paper_links=tuple(
            DiscoveryPaperLink(
                get_paper_route_identifier(p.source, p.arxiv_id, int(p.id)),
                p.title,
                p.published,
                "",
            )
            for p in papers.results
        ),
        robots="noindex,follow" if dates else "index,follow",
    )


def catalog_page(db: Session, params) -> DiscoveryPage | None:
    offset = int(params.get("offset", "0"))
    if offset < 0 or offset > 1_000_000 or offset % PAGE_SIZE:
        return None
    filters = {axis: params[axis] for axis in AXES if params.get(axis)}
    labels = discovery_catalog.terms(db)
    if any(value not in labels.get(axis, {}) for axis, value in filters.items()):
        return None
    data = discovery_catalog.browse(db, filters, PAGE_SIZE, offset)
    if offset and not data["results"]:
        return None

    def path(at: int) -> str:
        query = urlencode({**filters, **({"offset": at} if at else {})})
        return "/catalog" + ("?" + query if query else "")

    navigation = [DiscoveryLink("/", "Trending research")]
    if offset:
        navigation.append(DiscoveryLink(path(offset - PAGE_SIZE), "Previous"))
    if offset + PAGE_SIZE < data["total"]:
        navigation.append(DiscoveryLink(path(offset + PAGE_SIZE), "Next"))
    description = CATALOG_DESCRIPTION
    selections = "; ".join(
        f"{axis}: {labels[axis][value]}" for axis, value in filters.items()
    )
    return DiscoveryPage(
        kind="Catalog",
        canonical_path=path(offset),
        title=f"{CATALOG_TITLE}{f' — Page {offset // PAGE_SIZE + 1}' if offset else ''} | Papers With Code Cyber",
        description=description,
        heading="Browse catalog",
        breadcrumbs=(),
        body_markdown=f"{description}\n\n{data['total']} papers."
        + (f"\n\n{selections}" if selections else ""),
        entity_links=tuple(navigation),
        robots="noindex,follow" if filters else "index,follow",
        paper_links=tuple(
            DiscoveryPaperLink(
                quote(p["reference"], safe=""),
                p["title"],
                None,
                " · ".join(
                    [
                        *p["facets"].get("year", []),
                        *[
                            labels.get("contribution", {}).get(v, v)
                            for v in p["facets"].get("contribution", [])
                        ],
                    ]
                ),
            )
            for p in data["results"]
        ),
    )


def catalog_count(db: Session) -> int:
    return db.scalar(text("SELECT count(*) FROM discovery_works"))


def sitemap_papers(db: Session, page: int):
    # Use the same identifiers as browse_catalog; keep each shard bounded.
    return db.execute(
        text(
            discovery_catalog.SELECT_WORK + " ORDER BY p.id LIMIT :limit OFFSET :offset"
        ),
        {"limit": SITEMAP_SIZE, "offset": page * SITEMAP_SIZE},
    ).mappings()
