"""Crawler-control documents that must never fall through to the SPA."""

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from backend.config import get_settings
from backend.services.public_site_service import public_origin

router = APIRouter()


def robots_policy(environment: str) -> tuple[str, dict[str, str]]:
    if environment.lower() == "staging":
        return (
            "User-agent: *\nDisallow: /\n",
            {"X-Robots-Tag": "noindex, nofollow", "Cache-Control": "no-store"},
        )
    return (
        f"User-agent: *\nAllow: /\nSitemap: {public_origin()}/sitemap.xml\n",
        {"Cache-Control": "public, max-age=300"},
    )


@router.api_route(
    "/robots.txt",
    methods=["GET", "HEAD"],
    response_class=PlainTextResponse,
    include_in_schema=False,
)
def get_robots() -> PlainTextResponse:
    body, headers = robots_policy(get_settings().environment)
    return PlainTextResponse(body, headers=headers)
