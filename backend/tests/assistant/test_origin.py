"""Unsafe assistant requests must be checked before assigning an identity."""

from uuid import uuid4

import pytest

from backend.config import get_settings
from backend.routers import assistant


@pytest.mark.parametrize("cookie", [None, "v" * 43, "invalid"])
@pytest.mark.parametrize("method,suffix,payload", [
    ("POST", "turn", {"question": "Hello"}),
    ("POST", "runs/{id}/feedback", {"rating": "good"}),
    ("PATCH", "conversations/{id}", {"title": "Rename"}),
    ("DELETE", "conversations/{id}", None),
])
@pytest.mark.parametrize("origin,fetch_site", [
    ("https://evil.test", None), (None, None), ("null", "same-origin"),
    ("https://evil.test", "same-origin"), ("http://testserver", "cross-site"),
    (None, "same-site"), (None, "cross-site"),
])
def test_untrusted_writes_never_issue_identity(client, monkeypatch, cookie, method, suffix, payload, origin, fetch_site):
    client.headers.pop("origin", None)
    headers = {}
    if cookie:
        headers["Cookie"] = f"{assistant.COOKIE_NAME}={cookie}"
    if origin is not None:
        headers["Origin"] = origin
    if fetch_site is not None:
        headers["Sec-Fetch-Site"] = fetch_site
    def forbidden(*args):
        pytest.fail("Identity issued before origin validation")
    monkeypatch.setattr(assistant.secrets, "token_urlsafe", forbidden)
    response = client.request(method, "/api/v1/assistant/" + suffix.format(id=uuid4()),
                              headers=headers, **({"json": payload} if payload else {}))
    assert response.status_code == 403
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("content_type", [None, "text/plain", "application/x-www-form-urlencoded"])
def test_body_requires_json_before_identity(client, monkeypatch, content_type):
    def forbidden(*args):
        pytest.fail("Identity issued before content-type validation")
    monkeypatch.setattr(assistant.secrets, "token_urlsafe", forbidden)
    response = client.post("/api/v1/assistant/turn", content='{"question":"Hello"}',
                           headers={"Content-Type": content_type} if content_type else {})
    assert response.status_code == 415
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("headers,public_origin", [
    ({"Origin": "http://testserver"}, ""),
    ({"Sec-Fetch-Site": "same-origin"}, ""),
    ({"Origin": "http://localhost:5173", "Host": "localhost:5173"}, ""),
    ({"Origin": "https://catalog.test", "Host": "backend.internal:8000"}, "https://catalog.test"),
])
def test_trusted_cookie_free_writes(client, monkeypatch, headers, public_origin):
    monkeypatch.setattr(get_settings(), "public_site_url", public_origin)
    client.headers.pop("origin", None)
    async def fake(*args):
        yield assistant.sse({"type": "done"})
    monkeypatch.setattr(assistant, "turn_events", fake)
    response = client.post("/api/v1/assistant/turn", content='{"question":"Hello"}',
                           headers={**headers, "Content-Type": "application/json; charset=utf-8"})
    assert response.status_code == 200
    assert assistant.COOKIE_NAME in response.headers["set-cookie"]


def test_delete_body_also_requires_json(client):
    response = client.request("DELETE", f"/api/v1/assistant/conversations/{uuid4()}", content="{}")
    assert response.status_code == 415
