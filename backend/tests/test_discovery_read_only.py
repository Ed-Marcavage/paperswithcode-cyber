import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.main import create_app
from backend.models.papers import PaperDateRange
from backend.routers import papers


@pytest.fixture
def discovery_client(monkeypatch):
    monkeypatch.setattr(get_settings(), "discovery_catalog", True)
    app = create_app()

    @app.api_route("/api/test/method", methods=["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"])
    def method_echo(request: Request):
        return {"method": request.method}

    return TestClient(app)


@pytest.mark.parametrize("path", ["/api/test/method", "/api%2Ftest/method", "/%61pi/test/method"])
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_discovery_rejects_writes_before_dispatch(discovery_client, path, method):
    response = discovery_client.request(method, path)
    assert response.status_code == 405
    assert response.headers["allow"] == "GET, HEAD, OPTIONS"


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_discovery_allows_read_methods(discovery_client, method):
    response = discovery_client.request(method, "/api%2Ftest/method")
    assert response.status_code == 200
    if method != "HEAD":
        assert response.json() == {"method": method}


def test_writes_still_reach_routes_outside_discovery_mode(monkeypatch):
    monkeypatch.setattr(get_settings(), "discovery_catalog", False)
    app = create_app()

    @app.post("/api/test/method")
    def write():
        return {"handled": True}

    response = TestClient(app).post("/api%2Ftest/method")
    assert response.json() == {"handled": True}


@pytest.mark.parametrize(
    ("discovery", "requested", "expected"),
    [(True, None, "keyword"), (True, "keyword", "keyword"), (False, None, None), (False, "hybrid", "hybrid")],
)
def test_search_mode_passed_to_retrieval(monkeypatch, discovery, requested, expected):
    monkeypatch.setattr(get_settings(), "discovery_catalog", discovery)
    monkeypatch.setattr(get_settings(), "paper_search_mode", "semantic")
    monkeypatch.setattr(papers.PaperService, "search_papers_page", lambda self, *args, mode, **kwargs: mode)
    mode = papers.search_papers("example", 1, 1, requested, False, PaperDateRange(), None)
    assert mode == expected


@pytest.mark.parametrize("mode", ["semantic", "hybrid"])
def test_discovery_rejects_explicit_nonkeyword_search(monkeypatch, mode):
    monkeypatch.setattr(get_settings(), "discovery_catalog", True)
    with pytest.raises(HTTPException) as exc:
        papers.search_papers("example", 1, 1, mode, False, PaperDateRange(), None)
    assert exc.value.status_code == 422
