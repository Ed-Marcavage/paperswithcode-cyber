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
    assert seen[-1] == {"tier": "featured", "post_type": "tool-or-release", "featured_first": True}
    assert client.get("/api/v1/catalog/papers").status_code == 200
    assert seen[-1] == {"tier": "", "post_type": "", "featured_first": False}
    assert client.get("/api/v1/catalog/papers?tier=gold").status_code == 422


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
