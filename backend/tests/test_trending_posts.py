"""Industry posts on Trending: block selection, Posts ranking and routes."""
from datetime import date, timedelta

from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.database.connection import get_database_session
from backend.main import create_app
from backend.services import trending_posts
from backend.services.trending_posts import decayed_score, post_score, rank_feed, select_block

ANCHOR = date(2026, 11, 12)


def row(paper_id, days_old, tier="featured", depth=2, originality=2, relevance=3, harness=False, curated=False):
    post = {"tier": tier, "technical_depth": depth, "originality": originality,
            "agent_relevance": relevance, "agent_harness_engineering": harness}
    if curated:
        post["curated"] = True
    return {"paper_id": str(paper_id), "date_published": ANCHOR - timedelta(days=days_old), "post": post}


def ids(rows):
    return [r["paper_id"] for r in rows]


def test_score_adds_one_for_harness_engineering():
    assert post_score(row(1, 0, depth=3, originality=2)["post"]) == 5
    assert post_score(row(1, 0, depth=3, originality=2, harness=True)["post"]) == 6


def test_block_puts_curated_first_newest_first_then_scores():
    rows = [
        row(1, 1, depth=4, originality=4),
        row(2, 5, curated=True),
        row(3, 2, curated=True, tier="catalog", relevance=0),
        row(4, 3, depth=4, originality=3, harness=True),
        row(5, 0, depth=2, originality=2),
        row(6, 0, relevance=2, depth=4, originality=4),  # agent relevance too low
        row(7, 0, tier="catalog", depth=4, originality=4),  # not featured
        row(8, 4, depth=2, originality=2),
        row(9, 6, depth=1, originality=1),
    ]
    chosen, window = select_block(rows, ANCHOR)
    assert window == 14
    assert ids(chosen) == ["3", "2", "1", "4", "5", "8"]


def test_block_widens_to_30_days_when_14_give_too_few():
    rows = [row(1, 0), row(2, 13), row(3, 14), row(4, 20), row(5, 29), row(6, 30), row(7, 31)]
    chosen, window = select_block(rows, ANCHOR)
    assert window == 30
    assert ids(chosen) == ["1", "2", "3", "4", "5"]


def test_posts_view_halves_score_every_seven_days():
    assert decayed_score(row(1, 7)["post"], ANCHOR - timedelta(days=7), ANCHOR) == 2.0
    rows = [row(1, 14, depth=4, originality=4), row(2, 0, depth=1, originality=2), row(3, 7, depth=3, originality=3)]
    # 8/4 = 2.0, 3/1 = 3.0, 6/2 = 3.0 (tie broken by newer date)
    assert ids(rank_feed(rows, ANCHOR)) == ["2", "3", "1"]


def make_client(monkeypatch):
    monkeypatch.setattr(get_settings(), "discovery_catalog", True)
    app = create_app()
    app.dependency_overrides[get_database_session] = lambda: object()
    return TestClient(app)


def test_highlights_route(monkeypatch):
    seen = []

    def industry_block(db, limit):
        seen.append(limit)
        return {"anchor_date": "2026-11-12", "window_days": 14, "this_week": True, "results": []}

    monkeypatch.setattr(trending_posts, "industry_block", industry_block)
    client = make_client(monkeypatch)
    response = client.get("/api/v1/catalog/trending-posts/highlights")
    assert response.status_code == 200
    assert response.json()["window_days"] == 14
    assert seen == [6]
    assert client.get("/api/v1/catalog/trending-posts/highlights?limit=50").status_code == 422


def test_posts_feed_route_passes_paging_and_dates(monkeypatch):
    seen = []

    def posts_feed_ids(db, page, page_size, start_date, end_date):
        seen.append((page, page_size, start_date, end_date))
        return [], 0

    monkeypatch.setattr(trending_posts, "posts_feed_ids", posts_feed_ids)
    client = make_client(monkeypatch)
    response = client.get("/api/v1/catalog/trending-posts?page=2&page_size=10&start_date=2026-11-01")
    assert response.status_code == 200
    assert response.json()["results"] == []
    assert seen == [(2, 10, date(2026, 11, 1), None)]
