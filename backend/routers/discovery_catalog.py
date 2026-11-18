import time
from datetime import date
from functools import partial
from typing import Literal

import anyio
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.database.catalog_reads import catalog_sessions
from backend.database.connection import get_database_session
from backend.models.catalog_posts import POST_TYPES
from backend.models.database import Paper as DBPaper
from backend.models.papers import Papers
from backend.routers.paper_date_range import PaperDateRange, get_paper_date_range
from backend.services import catalog_posts, discovery_catalog, trending_posts
from backend.services.paper_feed_executor import PaperFeedExecutor
from backend.services.paper_service import PaperService

router = APIRouter(prefix="/catalog", tags=["Discovery catalog"])


@router.get("/filters", summary="List catalog filter values")
def filters(db: Session = Depends(get_database_session)):
    return discovery_catalog.terms(db)


@router.get("/post-types", summary="List reviewed post types")
def post_types():
    return {"post_type": sorted(POST_TYPES)}


@router.get("/posts", summary="Search reviewed industry posts")
async def posts(query: str = Query("", max_length=200), topic: str = Query("", max_length=100),
                subtopic: str = Query("", max_length=100), post_type: str = Query("", max_length=64),
                tier: Literal["", "featured", "catalog"] = "", publisher: str = Query("", max_length=160),
                min_agent_relevance: int | None = Query(None, ge=0, le=4),
                harness_engineering: bool | None = None, published_after: date | None = None,
                sort: Literal["score", "recent", "score_recent"] = "score",
                limit: int = Query(10, ge=1, le=10), sessions=Depends(catalog_sessions)):
    """Default relevance 3; only an omitted default may relax for sparse text searches.
    All-word English search, then broader reporting, then ranked any-word search;
    every relaxation is disclosed. No offset. At most 10 rows, within three seconds.
    """
    arguments = dict(query=query, topic=topic, subtopic=subtopic, post_type=post_type,
                     tier=tier, publisher=publisher, harness_engineering=harness_engineering,
                     published_after=published_after, sort=sort, limit=limit)
    if min_agent_relevance is not None:
        arguments["min_agent_relevance"] = min_agent_relevance
    try:
        with anyio.fail_after(catalog_posts.QUERY_SECONDS):
            result = await anyio.to_thread.run_sync(partial(
                catalog_posts.read_posts, arguments, sessions,
                time.monotonic() + catalog_posts.QUERY_SECONDS, validate_filters=True), abandon_on_cancel=True)
    except catalog_posts.InvalidPostFilter as error:
        raise HTTPException(422, error.detail) from None
    except (SQLAlchemyError, OSError, TimeoutError):
        raise HTTPException(503, "Post search is temporarily unavailable; this is not a zero-match result.") from None
    return {**result, "results": [{**row, "summary": row["tldr"]} for row in result["results"]]}


@router.get("/metadata", summary="Compact metadata for up to 25 catalog works")
async def metadata(references: str = Query(..., max_length=600,
                   pattern=r"^(?:[1-9][0-9]{0,18}|[0-9]{4}\.[0-9]{4,5})(?:,(?:[1-9][0-9]{0,18}|[0-9]{4}\.[0-9]{4,5})){0,24}$"),
                   sessions=Depends(catalog_sessions)):
    try:
        with anyio.fail_after(3):
            return await anyio.to_thread.run_sync(discovery_catalog.compact_metadata,
                                                 references.split(","), sessions, abandon_on_cancel=True)
    except (SQLAlchemyError, OSError, TimeoutError):
        raise HTTPException(503, "Catalog metadata is temporarily unavailable.") from None


@router.get("/papers", summary="Browse papers by catalog filters")
def papers(topic: str = "", target: str = "", contribution: str = "", kind: str = "",
           year: str = "", limit: int = Query(25, ge=1, le=100),
           offset: int = Query(0, ge=0), include_facet_counts: bool = False,
           tier: Literal["", "featured", "catalog"] = Query("", description="Industry post tier"),
           post_type: str = Query("", max_length=64, description="Industry post type slug"),
           order: Literal["", "featured"] = Query("", description="`featured` lists featured posts first"),
           min_agent_relevance: int | None = Query(
               None, ge=0, le=4,
               description="Leave out industry posts whose review agent relevance (0-4) is below this. "
                           "Papers are not filtered; add `kind=post` for posts only. Trending uses "
                           f"{trending_posts.MIN_AGENT_RELEVANCE}."),
           db: Session = Depends(get_database_session)):
    facets = dict(topic=topic, target=target, contribution=contribution, kind=kind, year=year)
    return discovery_catalog.browse(db, facets, limit, offset, include_facet_counts,
                                    tier=tier, post_type=post_type, featured_first=order == "featured",
                                    min_agent_relevance=min_agent_relevance)


@router.get("/trending-posts/highlights", summary="Editor's picks for the top of Trending")
def trending_post_highlights(limit: int = Query(trending_posts.PICKS_LIMIT, ge=1, le=12),
                             db: Session = Depends(get_database_session)):
    """Editor's picks: the owner's first pinned catalog works in pin order (three by default,
    as the block above Trending shows), with each work's preview image address (`thumbnail_url`)."""
    return trending_posts.industry_block(db, limit)


@router.get("/trending-posts", response_model=Papers, summary="Featured industry posts ranked for Trending")
def trending_posts_feed(page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=100),
                        include_resources: bool = False,
                        date_range: PaperDateRange = Depends(get_paper_date_range),
                        db: Session = Depends(get_database_session)):
    """Reviewed posts whose featured tier and agent relevance meet Trending's threshold, and reviewed pins after
    the Editor's picks block, ranked by review score halved for every 7 days since publication.
    The block's picks are left out."""
    ids, total = trending_posts.posts_feed_ids(db, page, page_size, date_range.start_date, date_range.end_date)
    by_id = {paper.id: paper for paper in db.query(DBPaper).filter(DBPaper.id.in_(ids))} if ids else {}
    service = PaperService(db)
    rows = [by_id[paper_id] for paper_id in ids if paper_id in by_id]
    return PaperFeedExecutor(service).page(rows, count=total, page=page, page_size=page_size,
                                           include_resources=include_resources)


@router.get("/repositories/{owner}/{name}", summary="Catalog works citing one repository, by role")
def repository_references(owner: str, name: str, db: Session = Depends(get_database_session)):
    """Papers and industry posts linked to the GitHub repository `owner/name` (any case),
    grouped by the reviewed role: original (the work's own code), target, supporting,
    dependency; links without a reviewed role are `unspecified`. Each work carries the
    review's evidence sentence and the exact link it cites."""
    result = discovery_catalog.repository_references(db, owner, name)
    if result is None:
        raise HTTPException(404, "Repository is not in the catalog")
    return result


@router.get("/papers/{reference}", summary="Get paper facets and artifact")
def paper(reference: str, db: Session = Depends(get_database_session)):
    row = discovery_catalog.work(db, reference)
    if row is None:
        raise HTTPException(404, "Paper has no curated catalog record")
    return dict(row)


@router.get("/papers/{reference}/text", response_class=PlainTextResponse, summary="Read cached paper text")
def document(reference: str, db: Session = Depends(get_database_session)):
    body = discovery_catalog.paper_text(db, reference)
    if body is None:
        raise HTTPException(404, "Paper has no curated catalog record")
    return PlainTextResponse(body, headers={"X-Content-Type-Options": "nosniff"})


@router.get("/papers/{paper_id}/preview/{digest}.jpg", include_in_schema=False)
def preview(paper_id: int, digest: str, db: Session = Depends(get_database_session)):
    data = discovery_catalog.preview(db, paper_id, digest)
    if data is None:
        raise HTTPException(404, "Preview unavailable")
    return Response(data, media_type="image/jpeg", headers={
        "Cache-Control": "public, max-age=31536000, immutable",
        "X-Content-Type-Options": "nosniff",
    })
