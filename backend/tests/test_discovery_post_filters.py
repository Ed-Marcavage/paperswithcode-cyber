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
