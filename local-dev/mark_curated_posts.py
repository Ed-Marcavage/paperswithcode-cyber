"""Pin catalog works and curate reviewed industry-post display fields.

Input: local-dev/curated_posts.json, edited by hand: {"pinned": [url, ...],
"posts": [{url, company, title}, ...]} (a bare list of posts is also accepted).
URLs are normalised for scheme, `www.`, fragment, trailing slash and arXiv
versions. `pinned` matches any catalog work and sets its curated_pin column
(1 for the first URL). The first three pins are Trending's Editor's picks.
`posts` matches only reviewed posts and sets `curated: true`, `curated_company`
and `curated_title` in post_details. Pins are also mirrored into existing
post reviews, even when absent from `posts`; NULL post_details stays NULL.
Works no longer listed lose their curated fields and pins. A rerun changes nothing.
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
    """Compare URLs without scheme, `www.`, fragment, case, slash or arXiv version."""
    value = url.strip().split("#", 1)[0].lower()
    value = re.sub(r"^https?://", "", value)
    value = re.sub(r"^www\.", "", value)
    value = value.rstrip("/")
    return re.sub(r"^(arxiv\.org/abs/.+?)v\d+$", r"\1", value)


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
        if not re.match(r"^https?://", url.strip()):
            raise ValueError(f"Pinned url must start with http:// or https://: {url}")
        key = normalize_url(url)
        fields = entries.setdefault(key, {})
        if "curated_pin" in fields:
            raise ValueError(f"Duplicate pinned url: {url}")
        fields["curated_pin"] = position
    return entries


def match(entries: dict[str, dict], posts: list[tuple[str, str]]) -> tuple[dict[str, dict], list[str]]:
    """Map catalog IDs to curated fields; return them and the manifest URLs left unmatched."""
    urls = {catalog_id: normalize_url(source_url) for catalog_id, source_url in posts}
    matched = {catalog_id: entries[url] for catalog_id, url in urls.items() if url in entries}
    return matched, sorted(entries.keys() - set(urls.values()))


def main():
    from backend.database.connection import db_manager

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, nargs="?", default=MANIFEST)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    data = json.loads(args.manifest.read_text())
    entries = load_manifest(data)
    original_urls = {normalize_url(entry["url"]): entry["url"] for entry in manifest_posts(data)}
    pinned_urls = {normalize_url(url): url for url in data.get("pinned", [])} if isinstance(data, dict) else {}
    db_manager.engine.echo = False
    with db_manager.session_local() as db:
        database, user = db.execute(text("SELECT current_database(), current_user")).one()
        if (database, user) != ("pwc_local", "pwc_local"):
            raise RuntimeError("Refusing any database/user except isolated pwc_local")
        db.execute(text("SELECT pg_advisory_xact_lock(27451504)"))
        migration = Path(__file__).resolve().parents[1] / "backend/database/migrations/add_discovery_catalog.sql"
        for statement in migration.read_text().split(";"):
            if statement.strip():
                db.execute(text(statement))
        works = db.execute(text("SELECT catalog_id, source_url FROM discovery_works ORDER BY catalog_id")).all()
        pinned, unmatched_pins = match(
            {url: fields for url, fields in entries.items() if "curated_pin" in fields},
            [tuple(row) for row in works],
        )
        pins_updated = 0
        for catalog_id, fields in sorted(pinned.items()):
            pins_updated += db.execute(text("""
                UPDATE discovery_works SET curated_pin = :pin
                 WHERE catalog_id = :id AND curated_pin IS DISTINCT FROM :pin
            """), {"id": catalog_id, "pin": fields["curated_pin"]}).rowcount
        pins_cleared = db.execute(text("""
            UPDATE discovery_works SET curated_pin = NULL
             WHERE curated_pin IS NOT NULL AND NOT (catalog_id = ANY(:ids))
        """), {"ids": sorted(pinned)}).rowcount
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
                   AND post_details IS NOT NULL
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
        "executed": args.execute, "manifest_entries": len(original_urls), "matched": len(matched),
        "updated": updated, "cleared": cleared,
        "unmatched_urls": [original_urls[url] for url in unmatched if url in original_urls],
        "pins_updated": pins_updated, "pins_cleared": pins_cleared,
        "unmatched_pinned_urls": [pinned_urls[url] for url in unmatched_pins],
    }, indent=2))


if __name__ == "__main__":
    main()
