"""Industry posts on Trending: Editor's picks, Posts ranking and routes."""
from datetime import date, timedelta

from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.database.connection import get_database_session
from backend.main import create_app
from backend.services import trending_posts
from backend.services.publishers import publisher_name
from backend.services.trending_posts import (
    MIN_AGENT_RELEVANCE, agent_related, decayed_score, order_feed, post_score, rank_feed, select_picks,
)

ANCHOR = date(2026, 11, 12)


def row(paper_id, days_old, tier="featured", depth=2, originality=2, relevance=3, harness=False, curated=False,
        pin=None):
    post = {"tier": tier, "technical_depth": depth, "originality": originality,
            "agent_relevance": relevance, "agent_harness_engineering": harness}
    if curated or pin:
        post["curated"] = True
    if pin:
        post["curated_pin"] = pin
    return {"paper_id": str(paper_id), "date_published": ANCHOR - timedelta(days=days_old), "post": post,
            "source_url": f"https://example.com/{paper_id}"}


def ids(rows):
    return [r["paper_id"] for r in rows]


def test_score_adds_one_for_harness_engineering():
    assert post_score(row(1, 0, depth=3, originality=2)["post"]) == 5
    assert post_score(row(1, 0, depth=3, originality=2, harness=True)["post"]) == 6


def test_picks_are_the_first_three_pins_in_pin_order_whatever_their_date_or_review():
    rows = [row(1, 0, depth=4, originality=4), row(2, 90, pin=2, tier="catalog", relevance=0), row(3, 3, pin=1),
            row(4, 1, curated=True), row(5, 2, pin=4), row(6, 0, pin=3), row(7, 5, pin=6)]
    assert ids(select_picks(rows)) == ["3", "2", "6"]
    assert ids(select_picks(rows, limit=1)) == ["3"]
    assert select_picks([row(1, 0), row(2, 0, curated=True)]) == []


def test_feed_ranks_later_pins_like_any_post_and_leaves_out_the_picks():
    rows = [row(1, 0, pin=1), row(2, 0, pin=2), row(3, 0, pin=3),
            row(4, 20, pin=4, depth=4, originality=4),  # old: ranks low, no special place
            row(5, 1, pin=5, tier="catalog", relevance=1, depth=4, originality=4),  # pinned skips the feed's rules
            row(6, 0, depth=3, originality=3), row(7, 2, depth=2, originality=2),
            row(8, 0, relevance=2), row(9, 0, curated=True, tier="catalog")]
    ordered = order_feed(rows, ANCHOR, picks={"1", "2", "3"})
    assert ids(ordered) == ["5", "6", "7", "4"]


def test_publisher_name_prefers_curated_then_map_then_host():
    assert publisher_name("https://www.endorlabs.com/learn/x", "Endor Labs") == "Endor Labs"
    assert publisher_name("https://www.elastic.co/security-labs/blog/x") == "Elastic"
    assert publisher_name("https://projectzero.google/2026/10/x.html") == "Google"
    assert publisher_name("https://security.microsoft.com/x") == "Microsoft"
    assert publisher_name("https://unknown.example/post") == "unknown.example"
    assert publisher_name(None) is None


def test_posts_view_halves_score_every_seven_days():
    assert decayed_score(row(1, 7)["post"], ANCHOR - timedelta(days=7), ANCHOR) == 2.0
    rows = [row(1, 14, depth=4, originality=4), row(2, 0, depth=1, originality=2), row(3, 7, depth=3, originality=3)]
    # 8/4 = 2.0, 3/1 = 3.0, 6/2 = 3.0 (tie broken by newer date)
    assert ids(rank_feed(rows, ANCHOR)) == ["2", "3", "1"]


class FakeSession:
    """Answers anchor_date's scalar and the Posts view's row query."""

    def __init__(self, rows):
        self.rows = rows

    def scalar(self, statement):
        return ANCHOR

    def execute(self, statement, params=None):
        return type("Result", (), {"mappings": lambda _: iter(self.rows)})()


def test_threshold_is_three():
    assert MIN_AGENT_RELEVANCE == 3
    assert [agent_related({"agent_relevance": n}) for n in range(5)] == [False, False, False, True, True]
    assert not agent_related({})


def test_posts_view_lists_only_agent_related_posts():
    rows = [row(n, n, relevance=n % 5, depth=4) for n in range(10)]
    page, total = trending_posts.posts_feed(FakeSession(rows), page=1, page_size=3)
    assert total == 4  # relevance 3 or 4: papers 3, 4, 8, 9
    assert ids(page) == ["3", "4", "8"]
    assert page[0]["publisher"] == "example.com"
    assert page[0]["date_published"] == (ANCHOR - timedelta(days=3)).isoformat()
    assert trending_posts.posts_feed_ids(FakeSession(rows), page=2, page_size=3) == ([9], 4)


def test_posts_view_leaves_out_the_three_picks_on_every_page():
    rows = [row(n, n, pin=n, depth=4) for n in range(1, 6)] + [row(9, 0)]
    page, total = trending_posts.posts_feed(FakeSession(rows), page=1, page_size=10)
    assert ids(page) == ["4", "9", "5"]  # pins 4 and 5 ranked with the rest
    assert total == 3


def test_block_returns_the_picks_with_their_preview_and_heading():
    rows = [dict(row(n, n, pin=n), title=f"Post {n}", reference=str(n), thumbnail_url=f"/p/{n}.jpg")
            for n in (2, 1, 4, 3)]
    block = trending_posts.industry_block(FakeSession(rows))
    assert block["heading"] == "Editor's picks"
    assert block["pinned"] == 3
    assert ids(block["results"]) == ["1", "2", "3"]
    assert block["results"][0]["thumbnail_url"] == "/p/1.jpg"
    assert block["anchor_date"] == ANCHOR.isoformat()


def make_client(monkeypatch):
    monkeypatch.setattr(get_settings(), "discovery_catalog", True)
    app = create_app()
    app.dependency_overrides[get_database_session] = lambda: object()
    return TestClient(app)


def test_highlights_route(monkeypatch):
    seen = []

    def industry_block(db, limit):
        seen.append(limit)
        return {"anchor_date": "2026-11-12", "window_days": None, "this_week": False, "heading": "Editor's picks",
                "results": []}

    monkeypatch.setattr(trending_posts, "industry_block", industry_block)
    client = make_client(monkeypatch)
    response = client.get("/api/v1/catalog/trending-posts/highlights")
    assert response.status_code == 200
    assert response.json()["heading"] == "Editor's picks"
    assert seen == [3]
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
