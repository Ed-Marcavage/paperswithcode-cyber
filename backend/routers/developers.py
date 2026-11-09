from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.database.connection import get_database_session
from backend.models.developers import DeveloperProfile, Developers
from backend.services.discovery_developers import developer_profile, list_developers

router = APIRouter(prefix="/developers", tags=["developers"])


@router.get("/", response_model=Developers, response_model_exclude_unset=True)
def directory(
    q: str = Query("", max_length=100),
    topic: str = "", target: str = "", contribution: str = "",
    repository: str = Query("", max_length=250, description="Exact GitHub owner/name"),
    sort: Literal["repos", "stars"] = Query("repos", description="Rank by matching repo count or stars on matching owned repos"),
    include_facet_counts: bool = Query(False, description="Distinct developers per option with all other filters retained"),
    limit: int = Query(24, ge=1, le=100), offset: int = Query(0, ge=0),
    db: Session = Depends(get_database_session),
):
    """Find developers whose tracked repos link to a work matching every selected facet."""
    return list_developers(db, q, limit, offset, repository=repository, sort=sort,
                           filters=dict(topic=topic, target=target, contribution=contribution),
                           include_facet_counts=include_facet_counts)


@router.get("/{github_id}", response_model=DeveloperProfile)
def profile(github_id: int, db: Session = Depends(get_database_session)):
    result = developer_profile(db, github_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Developer not found")
    return result
