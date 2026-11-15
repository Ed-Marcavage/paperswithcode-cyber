"""Reads from the optional curated catalog, keyed to the native papers table."""
import json

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.services.publishers import PUBLISHER_ORGANIZATION_SQL, publisher_name


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
           w.document_text IS NOT NULL AS has_text, w.post_details AS post,
           """ + PUBLISHER_ORGANIZATION_SQL.format(paper_id="p.id") + """ AS publisher_organization
      FROM discovery_works w JOIN papers p ON p.id = w.paper_id
"""


def _with_publisher(row) -> dict:
    """A work row for the API: posts get `publisher` (organization, else host)."""
    row = dict(row)
    organization = row.pop("publisher_organization", None)
    if "post" in (row.get("facets") or {}).get("kind", []):
        row["publisher"] = publisher_name(row["source_url"], organization=organization)
    return row


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


def _post_where(tier: str, post_type: str, min_agent_relevance: int | None) -> str:
    """SQL conditions for the industry-post filters.

    ``min_agent_relevance`` drops posts reviewed below it (a post without a
    review score counts as 0). Papers and other non-post works have no
    post_details and stay; combine with ``kind=post`` to list posts only."""
    return "".join([
        " AND w.post_details ->> 'tier' = :tier" if tier else "",
        " AND w.post_details ->> 'post_type' = :post_type" if post_type else "",
        " AND (NOT w.facets -> 'kind' ? 'post'"
        " OR coalesce((w.post_details ->> 'agent_relevance')::int, 0) >= :min_agent_relevance)"
        if min_agent_relevance is not None else "",
    ])


def browse(db: Session, filters: dict, limit: int, offset: int, include_facet_counts: bool = False,
           tier: str = "", post_type: str = "", featured_first: bool = False,
           min_agent_relevance: int | None = None) -> dict:
    """Facet filters, plus optional industry-post filters (tier, post type, minimum agent
    relevance) and ordering."""
    params = {"facets": json.dumps({k: [v] for k, v in filters.items() if v}),
              "limit": limit, "offset": offset, "tier": tier, "post_type": post_type,
              "min_agent_relevance": min_agent_relevance}
    post_where = _post_where(tier, post_type, min_agent_relevance)
    where = " WHERE w.facets @> CAST(:facets AS jsonb)" + post_where
    order = "(w.post_details ->> 'tier' = 'featured') DESC NULLS LAST, " if featured_first else ""
    total = db.scalar(text("SELECT count(*) FROM discovery_works w" + where), params)
    rows = db.execute(text(SELECT_WORK + where + """
        ORDER BY """ + order + """p.date_published DESC NULLS LAST, p.id LIMIT :limit OFFSET :offset
    """), params).mappings()
    response = {"total": total, "results": [_with_publisher(row) for row in rows]}
    if include_facet_counts:
        response["facet_counts"] = _facet_counts(db, list(filters), params, post_where)
    return response


def work(db: Session, reference: str):
    row = db.execute(text(SELECT_WORK + """
        WHERE p.id::text = :ref OR p.arxiv_id = :ref
        ORDER BY p.is_latest_version DESC, p.id DESC LIMIT 1
    """), {"ref": reference}).mappings().first()
    return _with_publisher(row) if row is not None else None


REFERENCE_ROLES = ("original", "target", "supporting", "dependency", "unspecified")


def repository_references(db: Session, owner: str, name: str) -> dict | None:
    """One repository (owner/name, any case) and the catalog works citing it, grouped by role."""
    repository = db.execute(text("""
        SELECT r.id::text AS id, r.url, r.owner, r.name, r.num_stars, r.num_stars_updated_at
          FROM repositories r WHERE lower(r.url) = lower(:url) ORDER BY r.id LIMIT 1
    """), {"url": f"https://github.com/{owner}/{name}"}).mappings().first()
    if repository is None:
        return None
    rows = db.execute(text("""
        SELECT coalesce(pr.role, 'unspecified') AS role, pr.is_official, pr.evidence, pr.link_url,
               p.id::text AS paper_id, coalesce(p.arxiv_id, p.id::text) AS reference, p.title,
               p.date_published, w.facets -> 'kind' ->> 0 AS kind, w.source_url,
               """ + PUBLISHER_ORGANIZATION_SQL.format(paper_id="p.id") + """ AS publisher_organization
          FROM paper_repositories pr JOIN discovery_works w USING (paper_id) JOIN papers p ON p.id = pr.paper_id
         WHERE pr.repository_id = CAST(:id AS bigint)
         ORDER BY p.date_published DESC NULLS LAST, p.id
    """), {"id": repository["id"]}).mappings()
    groups: dict[str, list] = {}
    for row in rows:
        row = dict(row)
        organization = row.pop("publisher_organization")
        if row["kind"] == "post":
            row["publisher"] = publisher_name(row["source_url"], organization=organization)
        groups.setdefault(row.pop("role"), []).append(row)
    order = {role: index for index, role in enumerate(REFERENCE_ROLES)}
    references = {role: groups[role] for role in sorted(groups, key=lambda r: (order.get(r, len(order)), r))}
    return {"repository": dict(repository), "total": sum(len(v) for v in groups.values()),
            "references": references}


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
