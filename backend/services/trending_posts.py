"""Industry posts on the Trending page.

Two views over reviewed industry posts (discovery_works.post_details):

- ``industry_block``: the short list above the Trending feed. Posts the owner
  pinned (``curated_pin`` in post_details, from the curated manifest's
  ``pinned`` list) come first in pin order, whatever their date. Remaining
  slots take curated posts from the date window (newest first), then other
  featured posts with agent relevance of at least 3, ranked by ``post_score``
  and then recency.
- ``posts_feed``: the Trending feed's "Posts" view. Featured posts ranked by
  ``post_score`` halved for every ``DECAY_HALF_LIFE_DAYS`` since publication.

Ages and windows count back from ``ANCHOR_DATE``. The preview catalog is a
static snapshot, so the default anchor is the newest reviewed post's
publication date rather than today's date.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.services.publishers import publisher_name

# None anchors to the newest reviewed post's date; set a date to pin it.
ANCHOR_DATE: Optional[date] = None

BLOCK_LIMIT = 6
BLOCK_WINDOW_DAYS = 14
BLOCK_WIDE_WINDOW_DAYS = 30
THIS_WEEK_DAYS = 7
MIN_AGENT_RELEVANCE = 3
DECAY_HALF_LIFE_DAYS = 7

_POSTS = """
    SELECT p.id::text AS paper_id, coalesce(p.arxiv_id, p.id::text) AS reference,
           p.title, p.date_published, w.facets, w.source_url, w.post_details AS post
      FROM discovery_works w JOIN papers p ON p.id = w.paper_id
     WHERE w.facets -> 'kind' ? 'post' AND w.post_details IS NOT NULL
       AND p.date_published IS NOT NULL
"""


def anchor_date(db: Session) -> Optional[date]:
    if ANCHOR_DATE is not None:
        return ANCHOR_DATE
    return db.scalar(text("""
        SELECT max(p.date_published) FROM discovery_works w JOIN papers p ON p.id = w.paper_id
         WHERE w.facets -> 'kind' ? 'post' AND w.post_details IS NOT NULL
    """))


def post_score(post: dict) -> int:
    """Technical depth + originality, plus 1 for agent-harness engineering (0-9)."""
    return post["technical_depth"] + post["originality"] + (1 if post.get("agent_harness_engineering") else 0)


def _published_on(row: dict) -> date:
    value = row["date_published"]
    return value.date() if hasattr(value, "date") else value


def _pin(row: dict) -> Optional[int]:
    value = row["post"].get("curated_pin")
    return value if type(value) is int and value > 0 else None


def select_block(rows: list[dict], anchor: date, limit: int = BLOCK_LIMIT) -> tuple[list[dict], int]:
    """Pick the block's posts from candidate rows; return them and the window used (days).

    Pinned posts fill the first slots in pin order regardless of date; the date
    window only governs the slots left after them."""
    pinned = sorted((row for row in rows if _pin(row) is not None), key=lambda row: (_pin(row), row["paper_id"]))
    pinned = pinned[:limit]
    if len(pinned) >= limit:
        return pinned, BLOCK_WINDOW_DAYS
    rows = [row for row in rows if _pin(row) is None]
    window = BLOCK_WINDOW_DAYS
    for window in (BLOCK_WINDOW_DAYS, BLOCK_WIDE_WINDOW_DAYS):
        start = anchor - timedelta(days=window)
        in_window = [row for row in rows if start < _published_on(row) <= anchor]
        curated = sorted((row for row in in_window if row["post"].get("curated")),
                         key=lambda row: (_published_on(row), row["paper_id"]), reverse=True)
        others = sorted(
            (row for row in in_window if not row["post"].get("curated")
             and row["post"].get("tier") == "featured"
             and row["post"].get("agent_relevance", 0) >= MIN_AGENT_RELEVANCE),
            key=lambda row: (post_score(row["post"]), _published_on(row), row["paper_id"]),
            reverse=True,
        )
        chosen = (pinned + curated + others)[:limit]
        if len(chosen) >= limit:
            break
    return chosen, window


def decayed_score(post: dict, published: date, anchor: date) -> float:
    age = max((anchor - published).days, 0)
    return post_score(post) * 0.5 ** (age / DECAY_HALF_LIFE_DAYS)


def rank_feed(rows: list[dict], anchor: date) -> list[dict]:
    return sorted(rows, key=lambda row: (decayed_score(row["post"], _published_on(row), anchor),
                                         _published_on(row), row["paper_id"]), reverse=True)


def _serialize(row: dict) -> dict:
    return {**row, "date_published": _published_on(row).isoformat(),
            "publisher": publisher_name(row["source_url"], row["post"].get("curated_company"))}


def block_heading(pinned: int, shown: int, this_week: bool) -> str:
    """Heading for the block. Only an unpinned block makes a date claim."""
    if shown and pinned >= shown:
        return "Editor's picks from industry"
    if pinned:
        return "From industry"
    return "From industry this week" if this_week else "Recent from industry"


def industry_block(db: Session, limit: int = BLOCK_LIMIT) -> dict:
    anchor = anchor_date(db)
    if anchor is None:
        return {"anchor_date": None, "window_days": BLOCK_WINDOW_DAYS, "this_week": False, "pinned": 0,
                "heading": block_heading(0, 0, False), "results": []}
    rows = [dict(row) for row in db.execute(text(_POSTS + """
        AND ((p.date_published > :start AND p.date_published <= :anchor
              AND (w.post_details ->> 'tier' = 'featured' OR w.post_details ->> 'curated' = 'true'))
             OR w.post_details ? 'curated_pin')
    """), {"start": anchor - timedelta(days=BLOCK_WIDE_WINDOW_DAYS), "anchor": anchor}).mappings()]
    chosen, window = select_block(rows, anchor, limit)
    pinned = sum(1 for row in chosen if _pin(row) is not None)
    recent = sum(1 for row in chosen if anchor - timedelta(days=THIS_WEEK_DAYS) < _published_on(row) <= anchor)
    # "This week" only for an unpinned block with at least 3 posts from the last 7 days.
    this_week = pinned == 0 and recent >= 3
    return {
        "anchor_date": anchor.isoformat(),
        "window_days": window,
        "this_week": this_week,
        "pinned": pinned,
        "heading": block_heading(pinned, len(chosen), this_week),
        "results": [_serialize(row) for row in chosen],
    }


def posts_feed_ids(db: Session, page: int, page_size: int, start_date: Optional[date] = None,
                   end_date: Optional[date] = None) -> tuple[list[int], int]:
    """Featured post IDs for one page of the Posts view, and the total count."""
    anchor = anchor_date(db)
    if anchor is None:
        return [], 0
    rows = [dict(row) for row in db.execute(text(_POSTS + """
        AND w.post_details ->> 'tier' = 'featured'
        AND (CAST(:start AS date) IS NULL OR p.date_published >= :start)
        AND (CAST(:end AS date) IS NULL OR p.date_published <= :end)
    """), {"start": start_date, "end": end_date}).mappings()]
    ranked = rank_feed(rows, anchor)
    window = ranked[(page - 1) * page_size: page * page_size]
    return [int(row["paper_id"]) for row in window], len(ranked)
