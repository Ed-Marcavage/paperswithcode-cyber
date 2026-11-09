from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy.orm import Session

from backend.database.connection import get_database_session
from backend.services import discovery_catalog

router = APIRouter(prefix="/catalog", tags=["Discovery catalog"])


@router.get("/filters", summary="List catalog filter values")
def filters(db: Session = Depends(get_database_session)):
    return discovery_catalog.terms(db)


@router.get("/papers", summary="Browse papers by catalog filters")
def papers(topic: str = "", target: str = "", contribution: str = "", kind: str = "",
           year: str = "", limit: int = Query(25, ge=1, le=100),
           offset: int = Query(0, ge=0), include_facet_counts: bool = False,
           db: Session = Depends(get_database_session)):
    facets = dict(topic=topic, target=target, contribution=contribution, kind=kind, year=year)
    return discovery_catalog.browse(db, facets, limit, offset, include_facet_counts)


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
