import json

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.models.developers import DeveloperProfile, Developers
from backend.services.trending_posts import MIN_AGENT_RELEVANCE


# Work-level facets stay together through matching. Only credited (is_official)
# links count: a post citing a repository as target or dependency adds no facets. Collapse to one developer/repo
# before ranking so multiple linked works cannot inflate counts or star totals.
#
# A developer's agent-related works are the distinct works that credit one of their repositories
# (is_official: a post's "original" role, a paper's official implementation) and are research papers
# or posts whose review agent relevance is at least Trending's MIN_AGENT_RELEVANCE (no score counts
# as 0), as on the Organizations page. Repository-kind works and posts that only target, depend on or
# cite a repository as supporting code do not count. first_agent_work marks one row per
# developer/work, so a work linking several of a developer's repositories counts once.
WORK = """
    WITH work AS (
        SELECT d.github_id, d.login, d.github_repo_id, d.full_name, d.owns, d.commits,
               w.paper_id, w.facets, r.num_stars, r.num_stars_updated_at,
               (w.facets->'kind' ? 'paper' OR (w.facets->'kind' ? 'post' AND coalesce(
                   (w.post_details->>'agent_relevance')::numeric, 0) >= :min_agent_relevance)) AS agent_related
        FROM discovery_developer_work d
        JOIN discovery_github_repo_snapshots s USING (github_repo_id)
        JOIN repositories r ON r.id = s.repository_id
        JOIN paper_repositories pr USING (repository_id)
        JOIN discovery_works w USING (paper_id)
        WHERE pr.is_official AND strpos(lower(d.login), lower(:q)) > 0
          AND (:repository = '' OR lower(d.full_name) = lower(:repository))
    )
"""
MATCHED = WORK + """
    , flagged AS (
        SELECT *, agent_related AND row_number() OVER (
                   PARTITION BY github_id, paper_id ORDER BY github_repo_id) = 1 AS first_agent_work
        FROM work WHERE facets @> CAST(:filters AS jsonb)
    )
    , matched AS (
        SELECT DISTINCT ON (github_id, github_repo_id)
               github_id, login, github_repo_id, full_name, owns, commits,
               num_stars, num_stars_updated_at,
               bool_or(agent_related) OVER repo AS agent_repo,
               count(*) FILTER (WHERE first_agent_work) OVER repo AS agent_works
        FROM flagged
        WINDOW repo AS (PARTITION BY github_id, github_repo_id)
        ORDER BY github_id, github_repo_id, num_stars_updated_at DESC NULLS LAST
    )
"""
# "agent" (the default) ranks by agent-related works, then commits to the repositories those
# works credit, then the older orders: matching repositories, owned-repository stars, login.
ORDERS = {
    "agent": "agent_work_count DESC, sum(commits) FILTER (WHERE agent_repo) DESC NULLS LAST, "
             "repository_count DESC, owned_stars DESC NULLS LAST,",
    "stars": "owned_stars DESC NULLS LAST, repository_count DESC,",
    "repos": "repository_count DESC,",
}


def list_developers(db: Session, q: str, limit: int, offset: int, *, repository: str,
                    sort: str, filters: dict[str, str], include_facet_counts: bool) -> Developers:
    params = dict(q=q.strip().lstrip("@"), limit=limit, offset=offset, repository=repository.strip(),
                  filters=json.dumps({axis: [value] for axis, value in filters.items() if value}),
                  min_agent_relevance=MIN_AGENT_RELEVANCE)
    count = db.scalar(text(WORK + """
        SELECT count(DISTINCT github_id) FROM work WHERE facets @> CAST(:filters AS jsonb)
    """), params)
    rows = db.execute(text(MATCHED + f"""
        SELECT github_id, login, count(*) AS repository_count,
               sum(agent_works) AS agent_work_count,
               (array_agg(full_name ORDER BY owns DESC, commits DESC, lower(full_name)))[1] AS featured_repo,
               CASE WHEN bool_and(num_stars_updated_at IS NOT NULL) FILTER (WHERE owns)
                    THEN sum(num_stars) FILTER (WHERE owns) END AS owned_stars
        FROM matched GROUP BY github_id, login
        ORDER BY {ORDERS[sort]} lower(login), github_id
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
