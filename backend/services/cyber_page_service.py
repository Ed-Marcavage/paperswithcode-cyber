"""Cyber page models built from the same read services as the React catalog."""

from datetime import date
from urllib.parse import quote, urlencode

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.services import discovery_catalog
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
HOME_TITLE = "AI Pentesting Tools & Security Agent Harnesses | Papers With Code Cyber"
HOME_DESCRIPTION = "Explore AI pentesting tools, security agent harnesses, papers, code and benchmarks for vulnerability discovery, code audit, fuzzing and reverse engineering."
CATALOG_TITLE = "AI Pentesting Tools & Cybersecurity Research"
CATALOG_DESCRIPTION = "Find AI pentesting tools, security agent harnesses, papers and benchmarks. Filter cybersecurity research by topic, target and contribution."
FEED_DESCRIPTION = "Cyberintel collection · GitHub star growth, then total stars. Newly tracked repositories start with total-star ordering until enough observations exist. Stars describe the entire repository, not paper quality."


def homepage(db: Session, params) -> DiscoveryPage:
    dates = {
        key: date.fromisoformat(params[key])
        for key in ("start_date", "end_date")
        if params.get(key)
    }
    papers = PaperService(db).get_papers(
        page=1, page_size=20, order_by="trending", latest_only=True, **dates
    )
    return DiscoveryPage(
        kind="Cybersecurity research",
        canonical_path="/",
        title=HOME_TITLE,
        description=HOME_DESCRIPTION,
        heading="Trending Research",
        body_markdown=HOME_DESCRIPTION + "\n\n" + FEED_DESCRIPTION,
        breadcrumbs=(),
        entity_links=(
            DiscoveryLink("/catalog", "Browse catalog"),
            DiscoveryLink("/mcp", "Connect an agent"),
        ),
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
