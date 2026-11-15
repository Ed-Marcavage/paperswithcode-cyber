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

PAGE_SIZE = 25
SITEMAP_SIZE = 1000
AXES = ("topic", "target", "contribution", "kind", "year")
# Keep aligned with frontend/src/lib/cyberCopy.ts (cyberHomeTitle, cyberHomeDescription).
# "/" lists industry posts and papers, so both are named; the papers wording is unchanged.
HOME_TITLE = "AI Pentesting Tools & Security Agent Harnesses: Papers & Posts | Papers With Code Cyber"
HOME_DESCRIPTION = "Explore AI pentesting tools, security agent harnesses, industry posts, papers, code and benchmarks for vulnerability discovery, code audit, fuzzing and reverse engineering."
CATALOG_TITLE = "AI Pentesting Tools & Cybersecurity Research"
CATALOG_DESCRIPTION = "Find AI pentesting tools, security agent harnesses, papers and benchmarks. Filter cybersecurity research by topic, target and contribution."
# Keep aligned with frontend/src/lib/cyberCopy.ts (cyberTrendingIndustryNote,
# cyberTrendingPostsDescription, cyberTrendingPapersDescription).
INDUSTRY_NOTE = "The block at the top shows hand-picked industry engineering posts."
# React's Trending switch opens on posts (?kind=paper shows papers); the server page
# lists both feeds, posts first, so crawlers keep the paper links.
POSTS_HEADING = "Trending posts about AI agents"
POSTS_FEED_DESCRIPTION = "Industry posts · featured posts about AI agents, ranked by review scores (technical depth plus originality, plus 1 for agent-harness engineering), halved for every 7 days since publication."
PAPERS_FEED_DESCRIPTION = "Research papers · GitHub star growth, then total stars. Newly tracked repositories start with total-star ordering until enough observations exist. Stars describe the entire repository, not paper quality."


def _post_link(row: dict) -> DiscoveryPaperLink:
    """A Trending industry post (block or feed row) as a page link."""
    return DiscoveryPaperLink(
        quote(row["reference"], safe=""),
        row["post"].get("curated_title") or row["title"],
        date.fromisoformat(row["date_published"]),
        row.get("publisher") or "",
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
    # The same industry block React shows above the feed, so the links are crawlable.
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
        entity_links=(
            DiscoveryLink("/catalog", "Browse catalog"),
            DiscoveryLink("/mcp", "Connect an agent"),
        ),
        post_heading=POSTS_HEADING,
        post_links=tuple(_post_link(row) for row in posts),
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
