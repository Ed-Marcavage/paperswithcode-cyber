import json

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.models.developers import DeveloperProfile, Developers


# Work-level facets stay together through matching. Collapse to one developer/repo
# before ranking so multiple linked works cannot inflate counts or star totals.
WORK = """
    WITH work AS (
        SELECT d.github_id, d.login, d.github_repo_id, d.full_name, d.owns, d.commits,
               w.facets, r.num_stars, r.num_stars_updated_at
        FROM discovery_developer_work d
        JOIN discovery_github_repo_snapshots s USING (github_repo_id)
        JOIN repositories r ON r.id = s.repository_id
        JOIN paper_repositories pr USING (repository_id)
        JOIN discovery_works w USING (paper_id)
        WHERE strpos(lower(d.login), lower(:q)) > 0
          AND (:repository = '' OR lower(d.full_name) = lower(:repository))
    )
"""
MATCHED = WORK + """
    , matched AS (
        SELECT DISTINCT ON (github_id, github_repo_id)
               github_id, login, github_repo_id, full_name, owns, commits,
               num_stars, num_stars_updated_at
        FROM work WHERE facets @> CAST(:filters AS jsonb)
        ORDER BY github_id, github_repo_id, num_stars_updated_at DESC NULLS LAST
    )
"""


def list_developers(db: Session, q: str, limit: int, offset: int, *, repository: str,
                    sort: str, filters: dict[str, str], include_facet_counts: bool) -> Developers:
    params = dict(q=q.strip().lstrip("@"), limit=limit, offset=offset, repository=repository.strip(),
                  filters=json.dumps({axis: [value] for axis, value in filters.items() if value}))
    count = db.scalar(text(MATCHED + "SELECT count(DISTINCT github_id) FROM matched"), params)
    order = "owned_stars DESC NULLS LAST," if sort == "stars" else ""
    rows = db.execute(text(MATCHED + f"""
        SELECT github_id, login, count(*) AS repository_count,
               (array_agg(full_name ORDER BY owns DESC, commits DESC, lower(full_name)))[1] AS featured_repo,
               CASE WHEN bool_and(num_stars_updated_at IS NOT NULL) FILTER (WHERE owns)
                    THEN sum(num_stars) FILTER (WHERE owns) END AS owned_stars
        FROM matched GROUP BY github_id, login
        ORDER BY {order} repository_count DESC, lower(login), github_id
        LIMIT :limit OFFSET :offset
    """), params).mappings()
    result = Developers(count=count, results=list(rows))
    if include_facet_counts:
        counts = {axis: {} for axis in filters}
        for axis, value, total in db.execute(text(WORK + """
            SELECT axis, choice.value, count(DISTINCT github_id)
            FROM work CROSS JOIN unnest(CAST(:axes AS text[])) axis
            CROSS JOIN LATERAL (
                SELECT '' AS value UNION ALL SELECT jsonb_array_elements_text(facets -> axis)
            ) choice
            WHERE facets @> (CAST(:filters AS jsonb) - axis)
            GROUP BY axis, choice.value
        """), {**params, "axes": list(filters)}):
            counts[axis][value] = total
        result.facet_counts = counts
    return result


def developer_profile(db: Session, github_id: int) -> DeveloperProfile | None:
    rows = db.execute(text("""
        SELECT login, github_repo_id, full_name, owns, commits
        FROM discovery_developer_work WHERE github_id=:id
        ORDER BY owns DESC, commits DESC, lower(full_name)
    """), {"id": github_id}).mappings().all()
    if not rows:
        return None
    return DeveloperProfile(github_id=github_id, login=rows[0]["login"], repositories=rows)
