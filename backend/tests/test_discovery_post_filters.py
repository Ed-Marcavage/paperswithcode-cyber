"""Industry-post filters on the catalog browse API."""
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.database.connection import get_database_session
from backend.main import create_app
from backend.services import discovery_catalog


def test_post_filters_reach_the_service(monkeypatch):
    monkeypatch.setattr(get_settings(), "discovery_catalog", True)
    seen = []

    def browse(db, filters, limit, offset, include_facet_counts=False, **post_filters):
        seen.append(post_filters)
        return {"total": 0, "results": []}

    monkeypatch.setattr(discovery_catalog, "browse", browse)
    app = create_app()
    app.dependency_overrides[get_database_session] = lambda: object()
    client = TestClient(app)

    response = client.get("/api/v1/catalog/papers?kind=post&tier=featured&post_type=tool-or-release&order=featured")
    assert response.status_code == 200
    assert seen[-1] == {"tier": "featured", "post_type": "tool-or-release", "featured_first": True,
                        "min_agent_relevance": None}
    assert client.get("/api/v1/catalog/papers").status_code == 200
    assert seen[-1] == {"tier": "", "post_type": "", "featured_first": False, "min_agent_relevance": None}
    assert client.get("/api/v1/catalog/papers?tier=gold").status_code == 422
    assert client.get("/api/v1/catalog/papers?kind=post&min_agent_relevance=3").status_code == 200
    assert seen[-1]["min_agent_relevance"] == 3
    assert client.get("/api/v1/catalog/papers?min_agent_relevance=0").status_code == 200
    assert seen[-1]["min_agent_relevance"] == 0
    for bad in ("5", "-1", "high"):
        assert client.get(f"/api/v1/catalog/papers?min_agent_relevance={bad}").status_code == 422


def test_repository_references_route(monkeypatch):
    monkeypatch.setattr(get_settings(), "discovery_catalog", True)
    seen = []

    def repository_references(db, owner, name):
        seen.append((owner, name))
        if name == "missing":
            return None
        return {"repository": {"id": "1"}, "total": 1, "references": {"original": [{"paper_id": "7"}]}}

    monkeypatch.setattr(discovery_catalog, "repository_references", repository_references)
    app = create_app()
    app.dependency_overrides[get_database_session] = lambda: object()
    client = TestClient(app)

    response = client.get("/api/v1/catalog/repositories/NVIDIA/OpenShell")
    assert response.status_code == 200
    assert response.json()["references"]["original"] == [{"paper_id": "7"}]
    assert seen == [("NVIDIA", "OpenShell")]
    assert client.get("/api/v1/catalog/repositories/org/missing").status_code == 404


def test_work_rows_get_a_publisher_for_posts_only():
    post = {"facets": {"kind": ["post"]}, "source_url": "https://blog.talosintelligence.com/x/",
            "publisher_organization": None}
    assert discovery_catalog._with_publisher(post)["publisher"] == "Cisco"
    assert discovery_catalog._with_publisher({**post, "publisher_organization": "Linked"})["publisher"] == "Linked"
    paper = discovery_catalog._with_publisher({**post, "facets": {"kind": ["paper"]}})
    assert "publisher" not in paper and "publisher_organization" not in paper


def test_min_agent_relevance_filters_posts_and_keeps_papers():
    assert discovery_catalog._post_where("", "", None) == ""
    clause = discovery_catalog._post_where("", "", 0)
    assert clause == (" AND (NOT w.facets -> 'kind' ? 'post'"
                      " OR coalesce((w.post_details ->> 'agent_relevance')::int, 0) >= :min_agent_relevance)")
    assert discovery_catalog._post_where("featured", "", 3).startswith(" AND w.post_details ->> 'tier' = :tier AND (")


class RecordingSession:
    def __init__(self):
        self.statements = []

    def scalar(self, statement, params):
        self.statements.append((str(statement), params))
        return 0

    def execute(self, statement, params):
        self.statements.append((str(statement), params))
        return type("Result", (), {"mappings": lambda _: iter([]), "__iter__": lambda _: iter([])})()


def test_browse_applies_min_agent_relevance_to_rows_counts_and_facets():
    db = RecordingSession()
    discovery_catalog.browse(db, {"kind": "post"}, 10, 0, include_facet_counts=True, min_agent_relevance=3)
    assert len(db.statements) == 3
    for sql, params in db.statements:
        assert ">= :min_agent_relevance" in sql
        assert params["min_agent_relevance"] == 3
    db = RecordingSession()
    discovery_catalog.browse(db, {}, 10, 0)
    assert all("agent_relevance" not in sql for sql, _ in db.statements)
