from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy.orm import Session

from backend.database.connection import get_database_session
from backend.models.database import Paper as DBPaper
from backend.models.papers import Papers
from backend.routers.paper_date_range import PaperDateRange, get_paper_date_range
from backend.services import discovery_catalog, trending_posts
from backend.services.paper_feed_executor import PaperFeedExecutor
from backend.services.paper_service import PaperService

router = APIRouter(prefix="/catalog", tags=["Discovery catalog"])


@router.get("/filters", summary="List catalog filter values")
def filters(db: Session = Depends(get_database_session)):
    return discovery_catalog.terms(db)


@router.get("/papers", summary="Browse papers by catalog filters")
def papers(topic: str = "", target: str = "", contribution: str = "", kind: str = "",
           year: str = "", limit: int = Query(25, ge=1, le=100),
           offset: int = Query(0, ge=0), include_facet_counts: bool = False,
           tier: Literal["", "featured", "catalog"] = Query("", description="Industry post tier"),
           post_type: str = Query("", max_length=64, description="Industry post type slug"),
           order: Literal["", "featured"] = Query("", description="`featured` lists featured posts first"),
           db: Session = Depends(get_database_session)):
    facets = dict(topic=topic, target=target, contribution=contribution, kind=kind, year=year)
    return discovery_catalog.browse(db, facets, limit, offset, include_facet_counts,
                                    tier=tier, post_type=post_type, featured_first=order == "featured")


@router.get("/trending-posts/highlights", summary="Industry posts for the top of Trending")
def trending_post_highlights(limit: int = Query(trending_posts.BLOCK_LIMIT, ge=1, le=12),
                             db: Session = Depends(get_database_session)):
    """Curated posts first, then featured posts with agent relevance of at least 3, from the
    last 14 days before the newest post (30 days when 14 give too few)."""
    return trending_posts.industry_block(db, limit)


@router.get("/trending-posts", response_model=Papers, summary="Featured industry posts ranked for Trending")
def trending_posts_feed(page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=100),
                        include_resources: bool = False,
                        date_range: PaperDateRange = Depends(get_paper_date_range),
                        db: Session = Depends(get_database_session)):
    """Featured posts ranked by review score, halved for every 7 days since publication."""
    ids, total = trending_posts.posts_feed_ids(db, page, page_size, date_range.start_date, date_range.end_date)
    by_id = {paper.id: paper for paper in db.query(DBPaper).filter(DBPaper.id.in_(ids))} if ids else {}
    service = PaperService(db)
    rows = [by_id[paper_id] for paper_id in ids if paper_id in by_id]
    return PaperFeedExecutor(service).page(rows, count=total, page=page, page_size=page_size,
                                           include_resources=include_resources)


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
