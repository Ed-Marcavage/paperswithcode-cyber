"""Industry posts on the Trending page: the feed's "Posts" view.

The owner's pinned posts (``curated_pin`` in post_details, from the curated
manifest's ``pinned`` list) lead the feed in pin order, whatever their date,
tier or agent relevance; they are the site's "Editor's picks". After them come
featured posts with agent relevance of at least ``MIN_AGENT_RELEVANCE``, ranked
by ``post_score`` halved for every ``DECAY_HALF_LIFE_DAYS`` since publication,
with the pinned posts left out so nothing is listed twice.

Pinned posts take the first slots of the first page only (at most one page of
them). A date window keeps only posts published inside it, pinned or not; the
pinned posts inside the window still come first. Posts marked ``curated`` but
not pinned get no special place. Everything else stays in the catalog and
search; it is just not on Trending.

Ages count back from ``ANCHOR_DATE``. The preview catalog is a static
snapshot, so the default anchor is the newest reviewed post's publication date
rather than today's date.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.services.publishers import PUBLISHER_ORGANIZATION_SQL, publisher_name

# None anchors to the newest reviewed post's date; set a date to pin it.
ANCHOR_DATE: Optional[date] = None

# Trending lists posts that are not pinned only at this agent relevance (0-4) or above.
MIN_AGENT_RELEVANCE = 3
DECAY_HALF_LIFE_DAYS = 7

_POSTS = """
    SELECT p.id::text AS paper_id, coalesce(p.arxiv_id, p.id::text) AS reference,
           p.title, p.date_published, w.facets, w.source_url, w.post_details AS post,
           """ + PUBLISHER_ORGANIZATION_SQL.format(paper_id="p.id") + """ AS publisher_organization
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


def agent_related(post: dict, min_agent_relevance: int = MIN_AGENT_RELEVANCE) -> bool:
    """Agent relevance at least ``min_agent_relevance`` (the catalog API's parameter of the
    same name); the default is Trending's rule for posts that are not pinned."""
    return (post.get("agent_relevance") or 0) >= min_agent_relevance


def _published_on(row: dict) -> date:
    value = row["date_published"]
    return value.date() if hasattr(value, "date") else value


def pin(post: dict) -> Optional[int]:
    """The owner's pin number (1 leads the feed), or None for a post that is not pinned."""
    value = (post or {}).get("curated_pin")
    return value if type(value) is int and value > 0 else None


def decayed_score(post: dict, published: date, anchor: date) -> float:
    age = max((anchor - published).days, 0)
    return post_score(post) * 0.5 ** (age / DECAY_HALF_LIFE_DAYS)


def rank_feed(rows: list[dict], anchor: date) -> list[dict]:
    return sorted(rows, key=lambda row: (decayed_score(row["post"], _published_on(row), anchor),
                                         _published_on(row), row["paper_id"]), reverse=True)


def _serialize(row: dict) -> dict:
    row = dict(row)
    organization = row.pop("publisher_organization", None)
    return {**row, "date_published": _published_on(row).isoformat(),
            "publisher": publisher_name(row["source_url"], row["post"].get("curated_company"), organization)}


def order_feed(rows: list[dict], anchor: date, page_size: int) -> list[dict]:
    """The whole Posts view in order: pinned posts in pin order (at most ``page_size``,
    so they stay on the first page), then the ranked featured, agent-related posts
    that are not among them."""
    pinned = sorted((row for row in rows if pin(row["post"]) is not None),
                    key=lambda row: (pin(row["post"]), row["paper_id"]))[:page_size]
    leading = {row["paper_id"] for row in pinned}
    ranked = rank_feed([row for row in rows if row["paper_id"] not in leading
                        and row["post"].get("tier") == "featured" and agent_related(row["post"])], anchor)
    return pinned + ranked


def posts_feed(db: Session, page: int, page_size: int, start_date: Optional[date] = None,
               end_date: Optional[date] = None) -> tuple[list[dict], int]:
    """Rows for one page of the Posts view (pinned posts, then featured agent-related posts,
    ranked), and the total count. Rows inside ``start_date``..``end_date`` only, when given."""
    anchor = anchor_date(db)
    if anchor is None:
        return [], 0
    rows = [dict(row) for row in db.execute(text(_POSTS + """
        AND (w.post_details ->> 'tier' = 'featured' OR w.post_details ? 'curated_pin')
        AND (CAST(:start AS date) IS NULL OR p.date_published >= :start)
        AND (CAST(:end AS date) IS NULL OR p.date_published <= :end)
    """), {"start": start_date, "end": end_date}).mappings()]
    ordered = order_feed(rows, anchor, page_size)
    return [_serialize(row) for row in ordered[(page - 1) * page_size: page * page_size]], len(ordered)


def posts_feed_ids(db: Session, page: int, page_size: int, start_date: Optional[date] = None,
                   end_date: Optional[date] = None) -> tuple[list[int], int]:
    """Post IDs for one page of the Posts view, and the total count."""
    rows, total = posts_feed(db, page, page_size, start_date, end_date)
    return [int(row["paper_id"]) for row in rows], total
