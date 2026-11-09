"""Public Cyber HTML, Markdown and XML. Registered after API and paper routes."""

import re
from dataclasses import replace
from html import escape
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.database.connection import get_database_session
from backend.services import cyber_page_service as pages
from backend.services.content_negotiation_service import (
    prefers_markdown,
    public_page_headers,
)
from backend.services.discovery_html_service import render_discovery_shell
from backend.services.public_page_markdown_service import render_discovery_markdown
from backend.services.public_site_service import (
    cyber_shell,
    finish_cyber_document,
    public_origin,
)
from backend.services.spa_shell_service import load_index_html

router = APIRouter()


def not_found() -> Response:
    return HTMLResponse(
        '<!doctype html><title>Page not found | Papers With Code Cyber</title><meta name="robots" content="noindex"><main><h1>Page not found</h1><a href="/catalog">Browse catalog</a></main>',
        status_code=404,
        headers={"Cache-Control": "no-store"},
    )


@router.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
@router.api_route("/index.md", methods=["GET", "HEAD"], include_in_schema=False)
@router.api_route("/catalog", methods=["GET", "HEAD"], include_in_schema=False)
@router.api_route("/catalog.md", methods=["GET", "HEAD"], include_in_schema=False)
def public_page(
    request: Request, db: Session = Depends(get_database_session)
) -> Response:
    try:
        page = (
            pages.catalog_page
            if request.url.path.startswith("/catalog")
            else pages.homepage
        )(db, request.query_params)
    except ValueError:
        return not_found()
    if page is None:
        return not_found()
    if get_settings().environment.lower() == "staging":
        page = replace(page, robots="noindex,nofollow")
    headers = public_page_headers(page.canonical_url)
    headers["X-Robots-Tag"] = page.robots
    if request.url.path.endswith(".md") or prefers_markdown(
        request.headers.get("accept")
    ):
        return Response(
            render_discovery_markdown(page), media_type="text/markdown", headers=headers
        )
    shell = load_index_html()
    if shell is None:
        return HTMLResponse(
            "Frontend bundle is not available.",
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )
    html = render_discovery_shell(cyber_shell(shell), page)
    return HTMLResponse(
        finish_cyber_document(html, page.canonical_url), headers=headers
    )


def xml_document(kind: str, paths) -> Response:
    element = "sitemap" if kind == "sitemapindex" else "url"
    entries = "".join(
        f"<{element}><loc>{escape(public_origin() + path)}</loc></{element}>"
        for path in paths
    )
    headers = {"Cache-Control": "public, max-age=300"}
    if get_settings().environment.lower() == "staging":
        headers["X-Robots-Tag"] = "noindex, nofollow"
    return Response(
        f'<?xml version="1.0" encoding="UTF-8"?><{kind} xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{entries}</{kind}>',
        media_type="application/xml",
        headers=headers,
    )


@router.api_route("/sitemap.xml", methods=["GET", "HEAD"], include_in_schema=False)
def sitemap_index(db: Session = Depends(get_database_session)) -> Response:
    count = pages.catalog_count(db)
    return xml_document(
        "sitemapindex",
        [
            "/sitemaps/static.xml",
            *[
                f"/sitemaps/papers-{page}.xml"
                for page in range(
                    (count + pages.SITEMAP_SIZE - 1) // pages.SITEMAP_SIZE
                )
            ],
        ],
    )


@router.api_route(
    "/sitemaps/static.xml", methods=["GET", "HEAD"], include_in_schema=False
)
def static_sitemap(db: Session = Depends(get_database_session)) -> Response:
    return xml_document(
        "urlset",
        [
            "/",
            "/catalog",
            *[
                f"/catalog?offset={offset}"
                for offset in range(
                    pages.PAGE_SIZE, pages.catalog_count(db), pages.PAGE_SIZE
                )
            ],
        ],
    )


@router.api_route(
    "/sitemaps/papers-{page}.xml", methods=["GET", "HEAD"], include_in_schema=False
)
def paper_sitemap(page: str, db: Session = Depends(get_database_session)) -> Response:
    if not re.fullmatch(r"0|[1-9][0-9]{0,5}", page):
        return not_found()
    if int(page) * pages.SITEMAP_SIZE >= pages.catalog_count(db):
        return not_found()
    return xml_document(
        "urlset",
        (
            "/paper/" + quote(p["reference"], safe="")
            for p in pages.sitemap_papers(db, int(page))
        ),
    )


@router.api_route("/llms.txt", methods=["GET", "HEAD"], include_in_schema=False)
def llms() -> Response:
    return PlainTextResponse(
        (Path(__file__).resolve().parents[2] / "frontend/public/llms.txt").read_text(),
        headers={"Cache-Control": "public, max-age=300"},
    )


# Existing browser entry points. Assets, API, MCP transport and reader data are
# routed separately by nginx; an arbitrary URL must never become a 200 shell.
CLIENT_PATH = re.compile(
    r"/(?:papers|tasks(?:/[^/]+)?|task/[^/]+|methods(?:/[^/]+)?|frameworks|trends|conferences(?:/[^/]+){0,2}|organizations(?:/[^/]+)?|orgs/[^/]+(?:/[^/]+)?|authors/[0-9]+|benchmark/[^/]+|developers(?:/[^/]+)?|pdf/[^/]+|mcp|personal-agents|docs/api|privacy|following|x-trending|submit|saved|settings|ai-deadlines|astra-for-robotics|rate-limits|request-access|admin-dashboard|cron-dashboard|autonomous-operations|submissions|authorize-paper-edit/[^/]+|chat(?:/[^/]+)?|share/[^/]+)"
)


@router.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
def client_page(path: str) -> Response:
    if not CLIENT_PATH.fullmatch("/" + path):
        return not_found()
    shell = load_index_html()
    if shell is None:
        return HTMLResponse("Frontend bundle is not available.", status_code=503)
    return HTMLResponse(
        cyber_shell(shell),
        headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex,follow"},
    )
