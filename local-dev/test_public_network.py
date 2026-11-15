"""Destination and fallback coverage with no browser or external requests."""

import asyncio
import json
import socket
from types import SimpleNamespace

from PIL import Image
import pytest

import catalog_post_previews as catalog
import post_previews as previews
import refresh_post_previews as refresh
from public_network import SafeOutboundHttpError, validate_destination
from backend.services import safe_outbound_http_service as outbound


@pytest.mark.parametrize("address", [
    "0.0.0.0", "127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.1.1", "169.254.169.254",
    "100.64.0.1", "224.0.0.1", "255.255.255.255", "::", "::1", "fc00::1", "fd12::1",
    "fe80::1", "fe80::1%en0", "fec0::1", "ff02::1", "::ffff:127.0.0.1",
    "::ffff:10.1.2.3", "2002:7f00:1::", "64:ff9b::7f00:1",
])
def test_nonpublic_addresses(address):
    assert not outbound._address_is_public(address)


@pytest.mark.parametrize("address", ["8.8.8.8", "1.1.1.1", "2606:4700:4700::1111", "::ffff:8.8.8.8"])
def test_public_addresses(address):
    assert outbound._address_is_public(address)


def test_mixed_dns_answers_and_failed_resolution(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("fd00::1", 443, 0, 0)),
    ])
    with pytest.raises(SafeOutboundHttpError, match="not public"):
        validate_destination("https://example.com/page")
    def unresolved(*a, **kw):
        raise socket.gaierror()
    monkeypatch.setattr(socket, "getaddrinfo", unresolved)
    with pytest.raises(SafeOutboundHttpError, match="resolved"):
        validate_destination("https://example.com/page")


@pytest.mark.parametrize("url", ["file:///etc/passwd", "data:text/html,hi", "ftp://example.com/p", "http://127.0.0.1/",
                                      "http://[::1]/", "http://[::ffff:127.0.0.1]/", "http://169.254.169.254/"])
def test_refused_url_is_recorded_and_title_card_uses_no_network(url, monkeypatch, tmp_path):
    def forbidden(*a, **kw):
        pytest.fail("Unsafe destination reached a browser or artwork fetch")
    monkeypatch.setattr(previews.subprocess, "run", forbidden)
    report = previews.run_capture(url, tmp_path / "capture.png")
    assert report["rejected"] and not previews.retryable(report)
    card = Image.new("RGB", previews.CARD_SIZE)
    image, record = asyncio.run(previews.prepare_preview(url, "Title", forbidden, forbidden, lambda *a: card))
    assert image is card
    assert record["method"] == "title card"
    assert record["screenshot_rejected"].startswith("destination rejected:")
    assert record["artwork_note"].startswith("destination rejected:")


@pytest.mark.parametrize("kind", ["redirect", "image"])
def test_artwork_fallback_rejects_private_redirects_and_image_urls(monkeypatch, kind):
    # The real artwork service uses fetch_public_resource for both HTML and images.
    # Stub only the network hop; URL/redirect validation remains real.
    calls = []
    async def hop(url, **kwargs):
        calls.append(url)
        if kind == "redirect":
            return 302, "", b"", "http://[::1]/metadata"
        return 200, "text/html", b'<meta property="og:image" content="http://169.254.169.254/image.png">', None
    monkeypatch.setattr(outbound, "_fetch_one_hop", hop)
    image, note = asyncio.run(previews.publisher_artwork(previews.artwork_service(), "https://example.com/page"))
    assert image is None and note
    assert calls == ["https://example.com/page"]


def test_catalog_and_resolved_refresh_urls_share_destination_policy(monkeypatch, tmp_path):
    service = SimpleNamespace(_render_external_metadata_thumbnail=lambda *a: Image.new("RGB", previews.CARD_SIZE))
    monkeypatch.setattr(previews, "artwork_service", lambda: service)
    source = tmp_path / "bundle"
    source.mkdir()
    (source / "catalog.json").write_text(json.dumps({"rows": [{"id": "post-one", "kind": "post",
        "url": "file:///etc/passwd", "title": "Catalog input"}]}))
    output = tmp_path / "catalog-output"
    asyncio.run(catalog.prepare(source, output, use_screenshots=False))
    record = json.loads((output / "previews/report.json").read_text())[0]
    assert record["method"] == "title card" and "rejected" in record["screenshot_rejected"]
    monkeypatch.setattr(refresh, "resolve", lambda post, api: {**post, "url": "http://[::1]/", "title": "API input"})
    entries = asyncio.run(refresh.shoot(["1008"], tmp_path / "refresh-output", "http://unused", False))
    assert entries[0]["method"] == "title card" and "rejected" in entries[0]["screenshot_rejected"]
