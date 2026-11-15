"""Mark hand-picked industry posts as curated ("Editor's pick").

Input: local-dev/curated_posts.json, edited by hand: {"pinned": [url, ...],
"posts": [{url, company, title}, ...]} (a bare list of posts is also accepted).
Each URL is matched to a reviewed post (one with post_details) after normalising
scheme, `www.`, fragment and trailing slash. Matched posts get `curated: true`,
`curated_company` and `curated_title` in post_details; a post listed in
`pinned` also gets `curated_pin` (1 for the first URL), which fixes its place
in Trending's industry block. Every pinned URL must also be in `posts`. Posts
no longer listed lose those keys. A rerun with the same file changes nothing.
import_post_details.py keeps these keys when it rewrites post_details.
Preview rolls back; pass --execute to commit.
"""
import argparse
import json
import re
from pathlib import Path

from sqlalchemy import text

from import_post_details import CURATED_KEYS

MANIFEST = Path(__file__).resolve().with_name("curated_posts.json")


def normalize_url(url: str) -> str:
    """Compare URLs without scheme, `www.`, fragment, case or trailing slash."""
    value = url.strip().split("#", 1)[0].lower()
    value = re.sub(r"^https?://", "", value)
    value = re.sub(r"^www\.", "", value)
    return value.rstrip("/")


def manifest_posts(data) -> list:
    """The manifest's post list, from either the object or the bare-list form."""
    return data.get("posts") if isinstance(data, dict) else data


def load_manifest(data) -> dict[str, dict]:
    """Validate the manifest and key it by normalised URL."""
    pinned = data.get("pinned", []) if isinstance(data, dict) else []
    data = manifest_posts(data)
    if not isinstance(data, list):
        raise ValueError("Expected a list of {url, company, title} objects")
    if not isinstance(pinned, list) or not all(isinstance(url, str) and url.strip() for url in pinned):
        raise ValueError("Expected pinned to be a list of URLs")
    entries = {}
    for index, entry in enumerate(data):
        if not isinstance(entry, dict) or not all(
            isinstance(entry.get(key), str) and entry[key].strip() for key in ("url", "company", "title")
        ):
            raise ValueError(f"Entry {index} needs non-empty url, company and title")
        if not re.match(r"^https?://", entry["url"].strip()):
            raise ValueError(f"Entry {index} url must start with http:// or https://")
        key = normalize_url(entry["url"])
        if key in entries:
            raise ValueError(f"Duplicate url in entry {index}: {entry['url']}")
        entries[key] = {"curated": True, "curated_company": entry["company"].strip(),
                        "curated_title": entry["title"].strip()}
    for position, url in enumerate(pinned, start=1):
        key = normalize_url(url)
        if key not in entries:
            raise ValueError(f"Pinned url is not in posts: {url}")
        if "curated_pin" in entries[key]:
            raise ValueError(f"Duplicate pinned url: {url}")
        entries[key]["curated_pin"] = position
    return entries


def match(entries: dict[str, dict], posts: list[tuple[str, str]]) -> tuple[dict[str, dict], list[str]]:
    """Map catalog IDs to curated fields; return them and the manifest URLs left unmatched."""
    by_url = {}
    for catalog_id, source_url in posts:
        by_url.setdefault(normalize_url(source_url), catalog_id)
    matched = {by_url[url]: fields for url, fields in entries.items() if url in by_url}
    return matched, sorted(url for url in entries if url not in by_url)


def main():
    from backend.database.connection import db_manager

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, nargs="?", default=MANIFEST)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    data = json.loads(args.manifest.read_text())
    entries = load_manifest(data)
    original_urls = {normalize_url(entry["url"]): entry["url"] for entry in manifest_posts(data)}
    db_manager.engine.echo = False
    with db_manager.session_local() as db:
        database, user = db.execute(text("SELECT current_database(), current_user")).one()
        if (database, user) != ("pwc_local", "pwc_local"):
            raise RuntimeError("Refusing any database/user except isolated pwc_local")
        db.execute(text("SELECT pg_advisory_xact_lock(27451504)"))
        posts = db.execute(text("""
            SELECT catalog_id, source_url FROM discovery_works
             WHERE facets -> 'kind' ? 'post' AND post_details IS NOT NULL ORDER BY catalog_id
        """)).all()
        matched, unmatched = match(entries, [tuple(row) for row in posts])
        updated = 0
        for catalog_id, fields in sorted(matched.items()):
            updated += db.execute(text("""
                UPDATE discovery_works
                   SET post_details = (post_details - CAST(:keys AS text[])) || CAST(:fields AS jsonb)
                 WHERE catalog_id = :id
                   AND post_details IS DISTINCT FROM (post_details - CAST(:keys AS text[])) || CAST(:fields AS jsonb)
            """), {"id": catalog_id, "keys": list(CURATED_KEYS),
                   "fields": json.dumps(fields, ensure_ascii=False)}).rowcount
        cleared = db.execute(text("""
            UPDATE discovery_works SET post_details = post_details - CAST(:keys AS text[])
             WHERE post_details ?| CAST(:keys AS text[]) AND NOT (catalog_id = ANY(:ids))
        """), {"keys": list(CURATED_KEYS), "ids": sorted(matched)}).rowcount
        if args.execute:
            db.commit()
        else:
            db.rollback()
    print(json.dumps({
        "executed": args.execute, "manifest_entries": len(entries), "matched": len(matched),
        "updated": updated, "cleared": cleared, "unmatched_urls": [original_urls[url] for url in unmatched],
    }, indent=2))


if __name__ == "__main__":
    main()
