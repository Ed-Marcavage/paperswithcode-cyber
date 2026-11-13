"""Load reviewed industry-post fields into discovery_works.post_details.

Input: one or more JSON objects keyed by catalog ID (`industry-...`), one review
per post, as written by the industry-intake review (v2-fields.json); further
files (e.g. hand-entered reviews) are merged in and may not repeat an ID. A
review may carry `reviewed_by` (e.g. "manual" for a hand-written review), which
is stored; bulk reviews omit it. Only posts already
imported by import_catalog.py are updated; papers and repositories are never
touched. A post missing from the input has its details cleared, so a rerun with
the same file changes nothing. Preview rolls back; pass --execute to commit.
"""
import argparse
import json
from pathlib import Path

from sqlalchemy import text

from backend.database.connection import db_manager

TIERS = {"featured", "catalog"}
POST_TYPES = {
    "vulnerability-writeup", "exploit-walkthrough", "malware-or-threat-intel", "incident-postmortem",
    "tool-or-release", "benchmark-or-evaluation", "engineering-practice", "detection-engineering",
    "research-summary", "explainer-or-tutorial", "opinion-or-strategy", "other",
}
TIMELINESS = {"evergreen", "dated", "time_bound"}
REVIEWERS = {"manual"}
SCORES = ("technical_depth", "originality", "agent_relevance")
FLAGS = ("reports_benchmark_results", "agent_harness_engineering")
# Set by mark_curated_posts.py from curated_posts.json; a rerun here keeps them.
CURATED_KEYS = ("curated", "curated_company", "curated_title", "curated_pin")


def strings(value, where):
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise ValueError(f"Expected a list of strings in {where}")
    return [v.strip() for v in value]


def optional_text(value, where):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Expected text in {where}")
    return value.strip() or None


def post_details(catalog_id, review):
    """Validate one review and keep only the fields the site shows or may show."""
    def where(field):
        return f"{field} on {catalog_id}"

    if review.get("tier") not in TIERS:
        raise ValueError(f"Unknown {where('tier')}")
    if review.get("post_type") not in POST_TYPES:
        raise ValueError(f"Unknown {where('post_type')}")
    if review.get("timeliness") not in TIMELINESS | {None}:
        raise ValueError(f"Unknown {where('timeliness')}")
    for score in SCORES:
        value = review.get(score)
        if type(value) is not int or not 0 <= value <= 4:
            raise ValueError(f"Expected a 0-4 {where(score)}")
    for flag in FLAGS:
        if type(review.get(flag)) is not bool:
            raise ValueError(f"Expected a boolean {where(flag)}")
    if review.get("reviewed_by") not in REVIEWERS | {None}:
        raise ValueError(f"Unknown {where('reviewed_by')}")
    tldr = optional_text(review.get("tldr"), where("tldr"))
    if tldr is None:
        raise ValueError(f"Missing {where('tldr')}")
    entities = review.get("entities") or []
    if not isinstance(entities, list) or not all(
        isinstance(e, dict) and all(isinstance(e.get(k), str) for k in ("type", "name", "role")) for e in entities
    ):
        raise ValueError(f"Invalid {where('entities')}")
    details = {
        "tier": review["tier"],
        "post_type": review["post_type"],
        "tldr": tldr,
        "original_title": optional_text(review.get("original_title"), where("original_title")),
        "subtopics": strings(review.get("subtopics") or [], where("subtopics")),
        "authors": strings(review.get("authors") or [], where("authors")),
        "caveat": optional_text(review.get("caveat"), where("caveat")),
        "timeliness": review.get("timeliness"),
        **{score: review[score] for score in SCORES},
        **{flag: review[flag] for flag in FLAGS},
        "entities": [{k: e[k] for k in ("type", "name", "role")} for e in entities],
    }
    if review.get("reviewed_by"):
        details["reviewed_by"] = review["reviewed_by"]
    return details


def merge_reviews(documents) -> dict:
    """Merge review files keyed by catalog ID; an ID may appear in only one of them."""
    merged = {}
    for document in documents:
        if not isinstance(document, dict):
            raise ValueError("Expected an object keyed by catalog ID")
        repeated = sorted(merged.keys() & document.keys())
        if repeated:
            raise ValueError(f"Catalog IDs repeated across input files: {repeated[:5]}")
        merged.update(document)
    return merged


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fields", type=Path, nargs="+")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    reviews = merge_reviews(json.loads(path.read_text()) for path in args.fields)
    details = {catalog_id: post_details(catalog_id, review) for catalog_id, review in reviews.items()}
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
        posts = set(db.scalars(text("SELECT catalog_id FROM discovery_works WHERE facets -> 'kind' ? 'post'")))
        updated = 0
        for catalog_id in sorted(details.keys() & posts):
            # Keep the curated marker that mark_curated_posts.py manages.
            updated += db.execute(text("""
                UPDATE discovery_works w SET post_details = new.details
                  FROM (SELECT CAST(:details AS jsonb) || coalesce(
                               (SELECT jsonb_object_agg(key, value) FROM jsonb_each(post_details)
                                 WHERE key = ANY(CAST(:keep AS text[]))), '{}'::jsonb) AS details
                          FROM discovery_works WHERE catalog_id = :id) new
                 WHERE w.catalog_id = :id AND w.post_details IS DISTINCT FROM new.details
            """), {"id": catalog_id, "keep": list(CURATED_KEYS),
                   "details": json.dumps(details[catalog_id], ensure_ascii=False)}).rowcount
        cleared = db.execute(text("""
            UPDATE discovery_works SET post_details = NULL
             WHERE post_details IS NOT NULL AND NOT (catalog_id = ANY(:ids))
        """), {"ids": sorted(details.keys() & posts)}).rowcount
        if args.execute:
            db.commit()
        else:
            db.rollback()
    unmatched = sorted(details.keys() - posts)
    print(json.dumps({
        "executed": args.execute, "reviews": len(details), "posts_in_catalog": len(posts),
        "matched": len(details.keys() & posts), "updated": updated, "cleared": cleared,
        "posts_without_review": len(posts - details.keys()),
        "reviews_without_post": len(unmatched), "reviews_without_post_sample": unmatched[:10],
    }))


if __name__ == "__main__":
    main()
