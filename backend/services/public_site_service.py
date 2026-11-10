"""Canonical identity and visible initial documents for the Cyber catalog."""

import re
from html import escape
from urllib.parse import urlsplit, urlunsplit

from backend.config import get_settings

_LOADING_HEAD = """
<style>
[data-pwc-loading]{display:none}
html[data-pwc-app-loading] [data-pwc-initial-document]{display:none}
html[data-pwc-app-loading] [data-pwc-loading]{display:block;max-width:960px;margin:auto;padding:24px;font:16px/1.6 system-ui}
</style>
<script>
(function () {
  document.documentElement.setAttribute("data-pwc-app-loading", "");
  function reveal() {
    clearTimeout(timer);
    document.documentElement.removeAttribute("data-pwc-app-loading");
    window.removeEventListener("error", failed, true);
    window.removeEventListener("pwc-app-ready", reveal);
  }
  function failed(event) {
    if (event.target && event.target.tagName === "SCRIPT") reveal();
  }
  // Keep the readable document available if the app cannot load.
  var timer = setTimeout(reveal, 4000);
  window.addEventListener("error", failed, true);
  window.addEventListener("pwc-app-ready", reveal);
})();
</script>
"""


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
    """Use the same initial document for humans and crawlers."""
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
    if re.search(r"<main\b[^>]*data-pwc-initial-document", html):
        html = html.replace("</head>", _LOADING_HEAD + "</head>", 1)
        html = html.replace(
            '<div id="root">',
            '<div id="root"><div data-pwc-loading role="status">'
            "Loading Papers With Code Cyber…</div>",
            1,
        )
    alternate = escape(markdown_url(canonical), quote=True)
    return html.replace(
        "</head>",
        f'<link rel="alternate" type="text/markdown" href="{alternate}"></head>',
    )
