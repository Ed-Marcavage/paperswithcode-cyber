"""Industry posts on Trending: the Posts view (pinned posts first, then ranked) and its route."""
from datetime import date, timedelta

from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.database.connection import get_database_session
from backend.main import create_app
from backend.services import trending_posts
from backend.services.publishers import publisher_name
from backend.services.trending_posts import (
    MIN_AGENT_RELEVANCE, agent_related, decayed_score, order_feed, pin, post_score, rank_feed,
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
    """Answers anchor_date's scalar and the Posts view's row query, applying its SQL filters
    (featured or pinned, inside the date window)."""

    def __init__(self, rows):
        self.rows = rows

    def scalar(self, statement):
        return ANCHOR

    def execute(self, statement, params=None):
        start, end = (params or {}).get("start"), (params or {}).get("end")
        rows = [r for r in self.rows
                if (r["post"]["tier"] == "featured" or "curated_pin" in r["post"])
                and (start is None or r["date_published"] >= start)
                and (end is None or r["date_published"] <= end)]
        return type("Result", (), {"mappings": lambda _: iter(rows)})()


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


def test_pin_reads_positive_pin_numbers_only():
    assert pin({"curated_pin": 2}) == 2
    assert pin({"curated": True}) is None
    assert pin({"curated_pin": 0}) is None
    assert pin({"curated_pin": "1"}) is None


def test_pinned_posts_lead_in_pin_order_whatever_their_date_tier_or_relevance():
    rows = [
        row(1, 0, depth=4, originality=4),
        row(2, 90, pin=2),  # old
        row(3, 3, pin=1, relevance=0, tier="catalog"),  # neither featured nor agent-related
        row(4, 1, curated=True, depth=1, originality=1),  # curated, not pinned: ranked like any post
        row(5, 2, depth=3, originality=3),
        row(6, 0, relevance=2, depth=4, originality=4),  # not agent-related, not pinned
        row(7, 0, tier="catalog"),  # not featured, not pinned
    ]
    ordered = order_feed(rows, ANCHOR, page_size=30)
    assert ids(ordered) == ["3", "2", "1", "5", "4"]


def test_pinned_posts_are_not_repeated_in_the_ranked_rows():
    rows = [row(1, 0, depth=4, originality=4, pin=2), row(2, 0, depth=1, originality=1, pin=1), row(3, 1)]
    ordered = order_feed(rows, ANCHOR, page_size=30)
    assert ids(ordered) == ["2", "1", "3"]
    assert len(ids(ordered)) == len(set(ids(ordered)))


def test_pinned_posts_fill_the_first_page_only():
    rows = [row(n, n, depth=4, originality=4) for n in range(1, 8)] + [row(10 + n, 50, pin=n) for n in range(1, 4)]
    first, total = trending_posts.posts_feed(FakeSession(rows), page=1, page_size=5)
    second, _ = trending_posts.posts_feed(FakeSession(rows), page=2, page_size=5)
    assert total == 10
    assert ids(first) == ["11", "12", "13", "1", "2"]
    assert ids(second) == ["3", "4", "5", "6", "7"]
    assert not any(pin(r["post"]) for r in second)


def test_pins_beyond_one_page_fall_back_to_the_ranking():
    rows = [row(n, 0, pin=n) for n in range(1, 4)] + [row(4, 0, pin=4, relevance=0)]
    ordered = order_feed(rows, ANCHOR, page_size=2)
    # Pins 3 and 4 do not fit on the first page: 3 is ranked like any post, 4 is not agent-related.
    assert ids(ordered) == ["1", "2", "3"]


def test_a_date_window_keeps_only_pinned_posts_inside_it_and_they_still_lead():
    rows = [row(1, 2, pin=1), row(2, 40, pin=2), row(3, 1, depth=4, originality=4), row(4, 20)]
    week, total = trending_posts.posts_feed(
        FakeSession(rows), 1, 30, start_date=ANCHOR - timedelta(days=7), end_date=ANCHOR)
    assert (ids(week), total) == (["1", "3"], 2)
    older, _ = trending_posts.posts_feed(
        FakeSession(rows), 1, 30, start_date=ANCHOR - timedelta(days=60), end_date=ANCHOR - timedelta(days=10))
    assert ids(older) == ["2", "4"]


def make_client(monkeypatch):
    monkeypatch.setattr(get_settings(), "discovery_catalog", True)
    app = create_app()
    app.dependency_overrides[get_database_session] = lambda: object()
    return TestClient(app)


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


def test_the_separate_highlights_route_is_gone(monkeypatch):
    assert make_client(monkeypatch).get("/api/v1/catalog/trending-posts/highlights").status_code == 404
