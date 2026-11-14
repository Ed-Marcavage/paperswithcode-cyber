"""Publisher names for industry posts.

A post's publisher is the organization linked to it with role ``publisher``
(``paper_organizations.role``, written by local-dev/import_post_links.py).
The host-to-organization table those links come from is the reviewable data
file ``backend/config/publisher_organizations.json``; this module reads it for
posts that have no publisher link yet, so nothing breaks before an import.
A host not in the file is shown as the host. Keys are hosts without ``www.``;
a host also matches through its parent domains (``security.example.com`` uses
``example.com``).

Standard library only: the industry-intake export loads this file by path.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

MAPPING_FILE = Path(__file__).resolve().parents[1] / "config" / "publisher_organizations.json"

# SQL for the publisher organization's name of the work ``{paper_id}`` (a column
# expression). A reviewed manifest link wins over one derived from the host.
PUBLISHER_ORGANIZATION_SQL = """(
    SELECT o.name FROM paper_organizations po JOIN organizations o ON o.id = po.organization_id
     WHERE po.paper_id = {paper_id} AND po.role = 'publisher'
     ORDER BY po.source = 'publisher_host', o.id LIMIT 1)"""


def load_organizations(path: Path = MAPPING_FILE) -> list[dict]:
    """The file's organizations, checked: unique names, each host listed once."""
    organizations = json.loads(path.read_text())["organizations"]
    names, hosts = set(), set()
    for organization in organizations:
        name = organization["name"].strip()
        if not name or name.casefold() in names:
            raise ValueError(f"Blank or repeated organization name: {name!r}")
        names.add(name.casefold())
        for entry in organization["hosts"]:
            if entry != entry.strip().lower() or entry.startswith("www.") or "/" in entry or entry in hosts:
                raise ValueError(f"Host must be lower-case, without www. or a path, and listed once: {entry!r}")
            hosts.add(entry)
    return organizations


@lru_cache(maxsize=1)
def host_table() -> dict[str, str]:
    """Host -> organization name, from the mapping file."""
    return {entry: organization["name"] for organization in load_organizations() for entry in organization["hosts"]}


def host(url: Optional[str]) -> Optional[str]:
    """"https://www.wiz.io/blog/x" -> "wiz.io"."""
    if not url:
        return None
    name = (urlsplit(url).hostname or "").lower()
    return name[4:] if name.startswith("www.") else name or None


def organization_for_url(url: Optional[str], table: Optional[dict[str, str]] = None) -> Optional[str]:
    """The mapped organization for a post URL, or None when its host is not mapped."""
    name = host(url)
    if name is None:
        return None
    table = host_table() if table is None else table
    parts = name.split(".")
    for index in range(len(parts) - 1):
        mapped = table.get(".".join(parts[index:]))
        if mapped:
            return mapped
    return None


def publisher_name(url: Optional[str], curated_company: Optional[str] = None,
                   organization: Optional[str] = None) -> Optional[str]:
    """The company to show for a post: the curated name, the linked publisher
    organization, the mapped name, or the host."""
    if curated_company and curated_company.strip():
        return curated_company.strip()
    if organization and organization.strip():
        return organization.strip()
    return organization_for_url(url) or host(url)
