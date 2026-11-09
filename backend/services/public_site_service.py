"""Canonical identity and visible initial documents for the Cyber catalog."""

import re
from html import escape
from urllib.parse import urlsplit, urlunsplit

from backend.config import get_settings


def public_origin() -> str:
    settings = get_settings()
    return settings.public_site_url or (
        "https://paperswithcode-cyber.com"
        if settings.discovery_catalog
        else "https://paperswithcode.co"
    )


def site_name() -> str:
    return (
        "Papers With Code Cyber"
        if get_settings().discovery_catalog
        else "Papers with Code"
    )


def markdown_url(canonical: str) -> str:
    parts = urlsplit(canonical)
    path = "/index.md" if parts.path == "/" else parts.path + ".md"
    return urlunsplit(parts._replace(path=path))


def cyber_shell(shell: str) -> str:
    """Use the same visible document for humans and crawlers until React mounts."""
    if not get_settings().discovery_catalog:
        return shell
    shell = re.sub(r"html \[data-pwc-initial-document\][^}]+}", "", shell)
    shell = re.sub(
        r'<footer\b[^>]*id="initial-discovery-footer".*?</footer>',
        "",
        shell,
        flags=re.S,
    )
    shell = shell.replace("https://paperswithcode.co", public_origin())
    shell = shell.replace("Papers with Code", site_name())
    return shell.replace(
        "</head>",
        "<style>[data-pwc-initial-document]{max-width:960px;margin:auto;padding:24px;font:16px/1.6 system-ui} [data-pwc-initial-document] a{color:inherit}</style></head>",
    )


def finish_cyber_document(html: str, canonical: str) -> str:
    if not get_settings().discovery_catalog:
        return html
    html = html.replace("<main hidden ", "<main ")
    alternate = escape(markdown_url(canonical), quote=True)
    return html.replace(
        "</head>",
        f'<link rel="alternate" type="text/markdown" href="{alternate}"></head>',
    )
