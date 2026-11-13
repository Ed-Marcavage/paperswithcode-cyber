"""Reads from the optional curated catalog, keyed to the native papers table."""
import json

from sqlalchemy import text
from sqlalchemy.orm import Session


def terms(db: Session) -> dict:
    result = {}
    for axis, value, label in db.execute(text(
        "SELECT axis, value, label FROM discovery_terms ORDER BY axis, label"
    )):
        result.setdefault(axis, {})[value] = label
    return result


SELECT_WORK = """
    SELECT p.id::text AS paper_id, coalesce(p.arxiv_id, p.id::text) AS reference,
           p.title, w.facets, w.source_url, w.artifact_url,
           w.document_text IS NOT NULL AS has_text, w.post_details AS post
      FROM discovery_works w JOIN papers p ON p.id = w.paper_id
"""


def _facet_counts(db: Session, axes: list[str], params: dict, post_where: str) -> dict:
    """Each option replaces its own filter. The empty value clears that filter."""
    rows = db.execute(text("""
        SELECT axis.name, choice.value, count(DISTINCT w.paper_id)
          FROM unnest(CAST(:axes AS text[])) AS axis(name)
          JOIN discovery_works w ON w.facets @> (CAST(:facets AS jsonb) - axis.name)""" + post_where + """
          CROSS JOIN LATERAL (
              SELECT '' AS value
              UNION ALL
              SELECT jsonb_array_elements_text(w.facets -> axis.name)
          ) AS choice
         GROUP BY axis.name, choice.value
    """), {**params, "axes": axes})
    counts = {axis: {} for axis in axes}
    for axis, value, count in rows:
        counts[axis][value] = count
    return counts


def browse(db: Session, filters: dict, limit: int, offset: int, include_facet_counts: bool = False,
           tier: str = "", post_type: str = "", featured_first: bool = False) -> dict:
    """Facet filters, plus optional industry-post filters (tier, post type) and ordering."""
    params = {"facets": json.dumps({k: [v] for k, v in filters.items() if v}),
              "limit": limit, "offset": offset, "tier": tier, "post_type": post_type}
    post_where = "".join([
        " AND w.post_details ->> 'tier' = :tier" if tier else "",
        " AND w.post_details ->> 'post_type' = :post_type" if post_type else "",
    ])
    where = " WHERE w.facets @> CAST(:facets AS jsonb)" + post_where
    order = "(w.post_details ->> 'tier' = 'featured') DESC NULLS LAST, " if featured_first else ""
    total = db.scalar(text("SELECT count(*) FROM discovery_works w" + where), params)
    rows = db.execute(text(SELECT_WORK + where + """
        ORDER BY """ + order + """p.date_published DESC NULLS LAST, p.id LIMIT :limit OFFSET :offset
    """), params).mappings()
    response = {"total": total, "results": [dict(row) for row in rows]}
    if include_facet_counts:
        response["facet_counts"] = _facet_counts(db, list(filters), params, post_where)
    return response


def work(db: Session, reference: str):
    return db.execute(text(SELECT_WORK + """
        WHERE p.id::text = :ref OR p.arxiv_id = :ref
        ORDER BY p.is_latest_version DESC, p.id DESC LIMIT 1
    """), {"ref": reference}).mappings().first()


def paper_text(db: Session, reference: str) -> str | None:
    row = db.execute(text("""
        SELECT w.document_text, w.source_url FROM discovery_works w
        JOIN papers p ON p.id = w.paper_id WHERE p.id::text = :ref OR p.arxiv_id = :ref
        ORDER BY p.is_latest_version DESC, p.id DESC LIMIT 1
    """), {"ref": reference}).first()
    if row is None:
        return None
    return row.document_text or f"No cached text is available for this paper. Source: {row.source_url}"


def preview(db: Session, paper_id: int, digest: str) -> bytes | None:
    image = db.scalar(text("""
        SELECT jpeg FROM discovery_previews WHERE paper_id = :id AND digest = :digest
    """), {"id": paper_id, "digest": digest})
    return bytes(image) if image is not None else None
