"""Catalog picks on Trending, reviewed Posts ranking and routes."""
from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.database.connection import get_database_session
from backend.main import create_app
from backend.models.database import Paper as DBPaper
from backend.services import discovery_catalog, trending_posts
from backend.services.paper_relation_loader import PaperRelationLoader
from backend.services.paper_service import PaperService
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
            "curated_pin": pin, "kind": "post", "facets": {"kind": ["post"]}, "authors": [], "summary": None,
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
    """Apply the SQL population filters without a database."""

    def __init__(self, rows):
        self.rows = rows

    def scalar(self, statement):
        return ANCHOR

    def execute(self, statement, params=None):
        sql = str(statement)
        rows = self.rows
        if "WHERE w.facets -> 'kind' ? 'post'" in sql:
            assert "w.post_details IS NOT NULL" in sql
            assert "p.date_published IS NOT NULL" in sql
            assert "OR w.curated_pin IS NOT NULL" in sql
            rows = [r for r in rows if r["kind"] == "post" and r["post"] is not None
                    and r["date_published"] is not None
                    and (not params["start"] or r["date_published"] >= params["start"])
                    and (not params["end"] or r["date_published"] <= params["end"])]
        else:
            assert "WHERE w.curated_pin IS NOT NULL" in sql
            assert "post_details IS NOT NULL" not in sql
            assert "date_published IS NOT NULL" not in sql
            rows = [r for r in rows if r["curated_pin"] is not None]
        assert "ORDER BY pa.author_order" in sql
        assert "coalesce(w.post_details ->> 'tldr', p.abstract) AS summary" in sql
        return type("Result", (), {"mappings": lambda _: iter(rows)})()


def mixed_picks():
    return [
        dict(row(20, 0, pin=2), post=None, date_published=None, title="Cyber Weapon Index", reference="20",
             publisher_organization="Booz Allen"),
        dict(row(10, 0, pin=1), kind="paper", facets={"kind": ["paper"]}, post=None,
             authors=["A. Researcher", "B. Researcher"], summary="Paper abstract.",
             title="Security research", reference="2609.18120", publisher_organization="Not a publisher"),
        dict(row(30, 0, pin=3), title="Reviewed post", reference="30", summary="Review summary."),
    ]


def test_mixed_picks_are_serialized_by_the_highlights_api(monkeypatch):
    rows = mixed_picks()
    rows[2]["post"].update(tldr="Review summary.", curated_company="Trail of Bits")
    db = FakeSession(rows)
    client = make_client(monkeypatch)
    client.app.dependency_overrides[get_database_session] = lambda: db
    response = client.get("/api/v1/catalog/trending-posts/highlights")
    assert response.status_code == 200
    paper, post, reviewed = response.json()["results"]
    assert [r["curated_pin"] for r in (paper, post, reviewed)] == [1, 2, 3]
    assert paper["kind"] == "paper" and paper["post"] is None and paper["publisher"] is None
    assert paper["authors"] == ["A. Researcher", "B. Researcher"]
    assert paper["summary"] == "Paper abstract."
    assert post["kind"] == "post" and post["post"] is None and post["publisher"] == "Booz Allen"
    assert post["date_published"] is None and post["authors"] == [] and post["summary"] is None
    assert reviewed["publisher"] == "Trail of Bits" and reviewed["summary"] == "Review summary."
    assert trending_posts.pick_paper_ids(db) == [10, 20, 30]


def test_posts_view_excludes_mixed_picks_and_later_unreviewed_pins():
    rows = mixed_picks() + [
        row(40, 20, pin=4, depth=4, originality=4),
        row(50, 1, pin=5, tier="catalog", relevance=0, depth=4, originality=4),
        dict(row(60, 0, pin=6), kind="paper", post=None),
        dict(row(70, 0, pin=7), post=None),
        row(80, 0, depth=3, originality=3),
    ]
    page, total = trending_posts.posts_feed(FakeSession(rows), page=1, page_size=10)
    assert ids(page) == ["50", "80", "40"] and total == 3
    page, total = trending_posts.posts_feed(
        FakeSession(rows), page=1, page_size=10, start_date=ANCHOR - timedelta(days=1), end_date=ANCHOR)
    assert ids(page) == ["50", "80"] and total == 2


def test_pick_order_uses_the_column_and_numeric_id_ties():
    stale = row(1, 0)
    stale["post"]["curated_pin"] = 1
    assert ids(select_picks([row(10, 0, pin=2), row(2, 0, pin=2), stale])) == ["2", "10"]


@pytest.mark.parametrize("kind", ["paper", "post"])
def test_paper_api_loads_pin_without_a_review(monkeypatch, kind):
    monkeypatch.setattr(get_settings(), "discovery_catalog", True)
    db = MagicMock()
    db.execute.return_value = [(10, [], kind, 1, None, None)]
    query = db.query.return_value
    for method in ("join", "filter", "order_by", "group_by", "select_from"):
        getattr(query, method).return_value = query
    query.all.return_value = []
    relations = PaperRelationLoader(db).load_cards([10])
    assert "w.curated_pin" in str(db.execute.call_args.args[0])
    paper = DBPaper(id=10, title="Pinned work", source="external", source_url="https://example.com/work",
                    version="v1", is_latest_version=True, urls_extracted=False, citation_count=0)
    service = PaperService(db)
    monkeypatch.setattr(service, "_resolve_thumbnail_url", lambda paper: None)
    result = service._to_api_paper(paper, relations).model_dump()
    assert result["catalog_pin"] == 1 and result["catalog_kind"] == kind
    assert result["catalog_post"] is None


def test_catalog_browse_preserves_pin_without_a_review():
    db = MagicMock()
    db.scalar.return_value = 2
    db.execute.return_value.mappings.return_value = mixed_picks()[:2]
    result = discovery_catalog.browse(db, {}, 25, 0)
    assert "w.curated_pin" in str(db.execute.call_args.args[0])
    assert [r["curated_pin"] for r in result["results"]] == [2, 1]
    assert all(r["post"] is None for r in result["results"])


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
        return {"anchor_date": "2026-11-12", "window_days": 14, "this_week": False, "heading": "Editor's picks",
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
