"""
GitHub utility functions for URL parsing and repository operations.

Standard library only: the industry-intake export loads this file by path.
"""

import logging
import re
from typing import Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def strip_git_suffix(name: str) -> str:
    """Drop a clone-style ``.git`` suffix; GitHub forbids it in repo names."""
    return name[:-4] if name.lower().endswith(".git") else name


def parse_github_url(url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Parse GitHub URL to extract owner and repository name.

    Args:
        url: GitHub URL (e.g., "https://github.com/microsoft/DialoGPT")

    Returns:
        Tuple of (owner, name) or (None, None) if parsing fails

    Examples:
        >>> parse_github_url("https://github.com/microsoft/DialoGPT")
        ("microsoft", "DialoGPT")

        >>> parse_github_url("https://github.com/huggingface/transformers/tree/main/examples")
        ("huggingface", "transformers")

        >>> parse_github_url("https://github.com/wuzimeng/comp.git")
        ("wuzimeng", "comp")

        >>> parse_github_url("https://example.com/not-github")
        (None, None)
    """
    try:
        parsed = urlparse(url)
        if parsed.netloc != "github.com":
            return None, None

        path_parts = parsed.path.strip("/").split("/")
        if len(path_parts) >= 2:
            owner = path_parts[0]
            name = strip_git_suffix(path_parts[1])
            if owner and name:
                return owner, name

        return None, None

    except Exception as e:
        logger.debug(f"Error parsing GitHub URL {url}: {e}")
        return None, None


def normalize_github_url(url: str) -> Optional[str]:
    """
    Normalize GitHub URL to standard format with lowercase for case-insensitive comparison.

    GitHub URLs are case-insensitive in practice (they redirect), so we normalize to
    lowercase to avoid duplicate entries in the database.

    Args:
        url: GitHub URL in any format

    Returns:
        Normalized GitHub URL (lowercase) or None if invalid

    Examples:
        >>> normalize_github_url("https://github.com/microsoft/DialoGPT/tree/main/examples")
        "https://github.com/microsoft/dialogpt"

        >>> normalize_github_url("github.com/Microsoft/DialoGPT")
        "https://github.com/microsoft/dialogpt"

        >>> normalize_github_url("https://github.com/FaceBook/React")
        "https://github.com/facebook/react"
    """
    if not url:
        return None

    # Add https:// if missing
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    owner, name = parse_github_url(url)
    if owner and name:
        # Normalize to lowercase for case-insensitive comparison
        # GitHub URLs are case-insensitive and redirect to the proper case
        return f"https://github.com/{owner.lower()}/{name.lower()}"

    return None


# First path segments on github.com that are GitHub pages, not an owner.
RESERVED_OWNERS = frozenset({
    "about", "account", "advisories", "apps", "blog", "codespaces", "collections", "contact",
    "customer-stories", "dashboard", "enterprise", "events", "explore", "features", "github-copilot",
    "issues", "join", "login", "marketplace", "new", "notifications", "organizations", "orgs",
    "pricing", "pulls", "readme", "search", "security", "settings", "site", "solutions", "sponsors",
    "stars", "topics", "trending", "users",
})
_OWNER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,38}", re.ASCII)
_NAME = re.compile(r"[A-Za-z0-9_.-]{1,100}", re.ASCII)


def github_repository(url: Optional[str]) -> Optional[Tuple[str, str]]:
    """The one repository a link names, as ``(owner, name)`` written in the link.

    Stricter than ``parse_github_url`` for reviewed links of any shape: it also
    reads ``www.github.com``, ``api.github.com/repos/...`` and raw file URLs,
    and rejects profiles, gists and GitHub's own pages (``/orgs/``,
    ``/advisories/``, ...). Sub-paths, queries and ``.git`` are dropped::

        >>> github_repository("https://github.com/Org/Repo.git/tree/main/sub?x=1")
        ("Org", "Repo")
        >>> github_repository("https://github.com/advisories/GHSA-xxxx") is None
        True
    """
    if not url or not url.strip():
        return None
    value = url.strip()
    if "://" not in value:
        value = f"https://{value}"
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    path = parsed.path
    if parsed.scheme not in ("http", "https"):
        return None
    if host == "api.github.com" and path.startswith("/repos/"):
        path = path[len("/repos"):]
    elif host not in ("github.com", "www.github.com", "raw.githubusercontent.com"):
        return None
    owner, name = parse_github_url(f"https://github.com{path}")
    if (not owner or not name or owner.lower() in RESERVED_OWNERS
            or not _OWNER.fullmatch(owner) or not _NAME.fullmatch(name) or name in (".", "..")):
        return None
    return owner, name


def repository_key(url: Optional[str]) -> Optional[str]:
    """Case-insensitive repository identity, ``"org/repo"``, or None."""
    found = github_repository(url)
    return f"{found[0]}/{found[1]}".lower() if found else None


def canonical_repository_url(owner: str, name: str) -> str:
    return f"https://github.com/{owner}/{name}"
