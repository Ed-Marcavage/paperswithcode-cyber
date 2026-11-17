"""Catalog picks and reviewed industry posts on the Trending page.

Two views over discovery_works:

- ``industry_block``: "Editor's picks", one row of the ``PICKS_LIMIT`` most
  important picks above the Trending feed: the first pinned catalog works in
  ``discovery_works.curated_pin`` order, whatever their kind, review or date.
- ``posts_feed``: the Trending feed's "Posts" view. Reviewed, dated posts only:
  featured posts with agent
  relevance of at least ``MIN_AGENT_RELEVANCE``, and the other pinned posts
  (pins after the block's), ranked together by ``post_score`` halved for every
  ``DECAY_HALF_LIFE_DAYS`` since publication. Pinned posts get no special
  position in the feed; their cards keep the "Editor's pick" badge. The block's
  picks are left out of both feeds, so nothing is listed twice.

Everything else stays in the catalog and search; it is just not on Trending.

Ages count back from ``ANCHOR_DATE``. The preview catalog is a static snapshot,
so the default anchor is the newest reviewed post's publication date rather
than today's date.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.services.publishers import PUBLISHER_ORGANIZATION_SQL, publisher_name

# None anchors to the newest reviewed post's date; set a date to pin it.
ANCHOR_DATE: Optional[date] = None

# The block shows this many picks: the first pins, in pin order.
PICKS_LIMIT = 3
# The highlights route once reported its date window; older clients expect a number.
LEGACY_WINDOW_DAYS = 14
PICKS_HEADING = "Editor's picks"
# Trending lists posts that are not pinned only at this agent relevance (0-4) or above.
MIN_AGENT_RELEVANCE = 3
DECAY_HALF_LIFE_DAYS = 7

_WORKS = """
    SELECT p.id::text AS paper_id, coalesce(p.arxiv_id, p.id::text) AS reference,
           p.title, p.date_published, p.thumbnail_url, w.facets, w.source_url, w.post_details AS post,
           w.curated_pin, w.facets -> 'kind' ->> 0 AS kind,
           coalesce(w.post_details ->> 'tldr', p.abstract) AS summary,
           ARRAY(SELECT a.name FROM paper_authors pa JOIN authors a ON a.id = pa.author_id
                  WHERE pa.paper_id = p.id ORDER BY pa.author_order) AS authors,
           """ + PUBLISHER_ORGANIZATION_SQL.format(paper_id="p.id") + """ AS publisher_organization
      FROM discovery_works w JOIN papers p ON p.id = w.paper_id
"""

_POSTS = _WORKS + """
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


def agent_related(post: dict, min_agent_relevance: int = MIN_AGENT_RELEVANCE) -> bool:
    """Agent relevance at least ``min_agent_relevance`` (the catalog API's parameter of the
    same name); the default is Trending's rule for posts that are not pinned."""
    return (post.get("agent_relevance") or 0) >= min_agent_relevance


def _published_on(row: dict) -> Optional[date]:
    value = row["date_published"]
    return value.date() if hasattr(value, "date") else value


def pin(row: dict) -> Optional[int]:
    """The catalog work's pin number, or None when it is not pinned."""
    return row.get("curated_pin")


def select_picks(rows: list[dict], limit: int = PICKS_LIMIT) -> list[dict]:
    """The block's works: the first ``limit`` pinned rows in pin order."""
    pinned = sorted((row for row in rows if pin(row) is not None),
                    key=lambda row: (pin(row), int(row["paper_id"])))
    return pinned[:limit]


def decayed_score(post: dict, published: date, anchor: date) -> float:
    age = max((anchor - published).days, 0)
    return post_score(post) * 0.5 ** (age / DECAY_HALF_LIFE_DAYS)


def rank_feed(rows: list[dict], anchor: date) -> list[dict]:
    return sorted(rows, key=lambda row: (decayed_score(row["post"], _published_on(row), anchor),
                                         _published_on(row), row["paper_id"]), reverse=True)


def order_feed(rows: list[dict], anchor: date, picks: set[str]) -> list[dict]:
    """The Posts view in order: featured agent-related posts and pinned posts, ranked together,
    without the block's picks."""
    return rank_feed([row for row in rows if row["paper_id"] not in picks and (
        pin(row) is not None
        or (row["post"].get("tier") == "featured" and agent_related(row["post"])))], anchor)


def _serialize(row: dict) -> dict:
    row = dict(row)
    organization = row.pop("publisher_organization", None)
    published = _published_on(row)
    post = row["post"] or {}
    return {**row, "date_published": published.isoformat() if published else None,
            "publisher": publisher_name(row["source_url"], post.get("curated_company"), organization)
            if row["kind"] == "post" else None}


def _pinned_rows(db: Session) -> list[dict]:
    return [dict(row) for row in db.execute(text(_WORKS + " WHERE w.curated_pin IS NOT NULL")).mappings()]


def pick_paper_ids(db: Session) -> list[int]:
    """Paper IDs of the block's picks, for exclusion from other Trending feeds."""
    return [int(row["paper_id"]) for row in select_picks(_pinned_rows(db))]


def industry_block(db: Session, limit: int = PICKS_LIMIT) -> dict:
    """Editor's picks above the Trending feed: the first ``limit`` pins, in pin order.

    ``anchor_date``, ``window_days`` and ``this_week`` keep the route's earlier shape;
    the block no longer depends on a date window."""
    chosen = select_picks(_pinned_rows(db), limit)
    anchor = anchor_date(db)
    return {
        "anchor_date": anchor.isoformat() if anchor else None,
        # Always numeric, as it was before the block stopped using a date window.
        "window_days": LEGACY_WINDOW_DAYS,
        "this_week": False,
        "pinned": len(chosen),
        "heading": PICKS_HEADING,
        "results": [_serialize(row) for row in chosen],
    }


def posts_feed(db: Session, page: int, page_size: int, start_date: Optional[date] = None,
               end_date: Optional[date] = None) -> tuple[list[dict], int]:
    """Rows for one page of the Posts view (featured agent-related and pinned posts, ranked,
    without the block's picks), and the total count. Rows inside ``start_date``..``end_date``
    only, when given."""
    anchor = anchor_date(db)
    if anchor is None:
        return [], 0
    rows = [dict(row) for row in db.execute(text(_POSTS + """
        AND (w.post_details ->> 'tier' = 'featured' OR w.curated_pin IS NOT NULL)
        AND (CAST(:start AS date) IS NULL OR p.date_published >= :start)
        AND (CAST(:end AS date) IS NULL OR p.date_published <= :end)
    """), {"start": start_date, "end": end_date}).mappings()]
    # The block ignores the date window, so its picks are found among all pins.
    picks = {str(paper_id) for paper_id in pick_paper_ids(db)}
    ordered = order_feed(rows, anchor, picks)
    return [_serialize(row) for row in ordered[(page - 1) * page_size: page * page_size]], len(ordered)


def posts_feed_ids(db: Session, page: int, page_size: int, start_date: Optional[date] = None,
                   end_date: Optional[date] = None) -> tuple[list[int], int]:
    """Post IDs for one page of the Posts view, and the total count."""
    rows, total = posts_feed(db, page, page_size, start_date, end_date)
    return [int(row["paper_id"]) for row in rows], total
