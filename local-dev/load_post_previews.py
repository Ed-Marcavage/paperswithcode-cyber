"""Load post previews from a refresh manifest into discovery_previews.

Input: the `manifest.json` that `refresh_post_previews.py shoot` wrote, with its
JPEGs beside it. Each post is matched by paper id (its catalog URL must equal
the manifest URL) or, for an entry without one, by its catalog URL. Like
import_catalog.py, a loaded preview is stored with `digest` = SHA-256 of the
JPEG bytes and `papers.thumbnail_url` becomes
`/api/v1/catalog/papers/{paper_id}/preview/{digest}.jpg`. A post whose
thumbnail was set by something else is skipped.

Dry run by default: only reads the database and prints what would change.
Pass --execute to write. Only the isolated pwc_local database is accepted.
"""
import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

from PIL import Image
from sqlalchemy import text

CARD_SIZE = (400, 550)
MAX_BYTES = 1024 * 1024


def preview_url(paper_id: int, digest: str) -> str:
    return f"/api/v1/catalog/papers/{paper_id}/preview/{digest}.jpg"


def read_manifest(path: Path) -> list:
    """Entries with their JPEG bytes, after checking each file against the manifest."""
    directory = path.parent.resolve()
    manifest = json.loads(path.read_text())
    if manifest.get("version") != 1:
        raise ValueError("Unsupported manifest version")
    entries = []
    for entry in manifest["posts"]:
        file = (directory / entry["file"]).resolve()
        if Path(entry["file"]).is_absolute() or not file.is_relative_to(directory) or not file.is_file():
            raise ValueError(f"Missing or invalid preview file for {entry['item']}")
        if file.stat().st_size > MAX_BYTES:
            raise ValueError(f"Preview over 1 MiB for {entry['item']}")
        data = file.read_bytes()
        if sha256(data).hexdigest() != entry["digest"]:
            raise ValueError(f"Preview bytes do not match the manifest digest for {entry['item']}")
        with Image.open(BytesIO(data)) as image:
            if image.format != "JPEG" or image.size != CARD_SIZE:
                raise ValueError(f"Expected a 400x550 JPEG for {entry['item']}")
        entries.append({**entry, "jpeg": data})
    return entries


def lookup(db, entry) -> list:
    """The catalog post(s) an entry refers to, with their current preview state."""
    return [dict(row) for row in db.execute(text("""
        SELECT w.paper_id, w.source_url, p.thumbnail_url, d.digest
          FROM discovery_works w JOIN papers p ON p.id = w.paper_id
          LEFT JOIN discovery_previews d ON d.paper_id = w.paper_id
         WHERE w.facets -> 'kind' ? 'post'
           AND (w.paper_id = CAST(:id AS bigint) OR (CAST(:id AS bigint) IS NULL AND w.source_url = :url))
    """), {"id": entry["paper_id"], "url": entry["url"]}).mappings()]


def plan(entry: dict, matches: list) -> dict:
    """What loading this entry would do, from the matching catalog rows."""
    base = {"item": entry["item"], "paper_id": entry["paper_id"], "method": entry.get("method")}
    if not matches:
        return {**base, "action": "skip", "reason": "not a post in this catalog"}
    if len(matches) > 1:
        return {**base, "action": "skip", "reason": "several posts share this URL"}
    current = matches[0]
    base["paper_id"] = current["paper_id"]
    if current["source_url"] != entry["url"]:
        return {**base, "action": "skip", "reason": "catalog URL differs from the manifest"}
    target = preview_url(current["paper_id"], entry["digest"])
    managed = f"/api/v1/catalog/papers/{current['paper_id']}/preview/"
    if current["thumbnail_url"] and not current["thumbnail_url"].startswith(managed):
        return {**base, "action": "skip", "reason": "thumbnail set by another source"}
    if current["digest"] == entry["digest"] and current["thumbnail_url"] == target:
        return {**base, "action": "unchanged"}
    return {**base, "action": "insert" if current["digest"] is None else "update",
            "digest": entry["digest"], "thumbnail_url": target}


def apply(db, step: dict, jpeg: bytes) -> None:
    db.execute(text("""
        INSERT INTO discovery_previews (paper_id, digest, jpeg) VALUES (:id, :digest, :jpeg)
        ON CONFLICT (paper_id) DO UPDATE SET digest = excluded.digest, jpeg = excluded.jpeg
        WHERE discovery_previews.digest <> excluded.digest
    """), {"id": step["paper_id"], "digest": step["digest"], "jpeg": jpeg})
    db.execute(text("""
        UPDATE papers SET thumbnail_url = :url WHERE id = :id AND thumbnail_url IS DISTINCT FROM :url
    """), {"id": step["paper_id"], "url": step["thumbnail_url"]})


def load(db, entries: list, execute: bool) -> list:
    """Plan every entry; write the changes only when `execute` is true. Does not commit."""
    database, user = db.execute(text("SELECT current_database(), current_user")).one()
    if (database, user) != ("pwc_local", "pwc_local"):
        raise RuntimeError("Refusing any database/user except isolated pwc_local")
    if execute:
        db.execute(text("SELECT pg_advisory_xact_lock(27451504)"))
    steps = []
    for entry in entries:
        step = plan(entry, lookup(db, entry))
        if execute and step["action"] in {"insert", "update"}:
            apply(db, step, entry["jpeg"])
        steps.append(step)
    return steps


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--execute", action="store_true", help="Write the previews (default: dry run)")
    args = parser.parse_args()
    entries = read_manifest(args.manifest)
    from backend.database.connection import db_manager

    db_manager.engine.echo = False
    with db_manager.session_local() as db:
        steps = load(db, entries, args.execute)
        if args.execute:
            db.commit()
        else:
            db.rollback()
    counts = {}
    for step in steps:
        counts[step["action"]] = counts.get(step["action"], 0) + 1
    print(json.dumps({"executed": args.execute, "posts": len(steps), "actions": counts, "steps": steps}, indent=2))


if __name__ == "__main__":
    main()
