"""Organization metrics for the curated catalog. Each tracked repository counts once."""

from sqlalchemy import text
from sqlalchemy.orm import Session
from backend.models.organizations import Organization


def with_catalog_metrics(
    db: Session, organizations: list[Organization]
) -> list[Organization]:
    if not organizations:
        return []
    # Paper attribution and repository ownership are separate relationships.
    # EXISTS limits ownership to cataloged repos without multiplying their stars
    # when several papers link to the same repo.
    rows = db.execute(
        text("""
        WITH kinds AS (
            SELECT po.organization_id,
                   count(*) FILTER (WHERE w.facets->'kind' ? 'paper') AS papers,
                   count(*) FILTER (WHERE w.facets->'kind' ? 'post') AS posts,
                   count(*) FILTER (WHERE w.facets->'kind' ? 'repository') AS tools
            FROM paper_organizations po JOIN discovery_works w ON w.paper_id=po.paper_id
            GROUP BY po.organization_id
        ), owned AS (
            SELECT o.id, count(*) AS repos,
                   CASE WHEN count(r.num_stars_updated_at) = count(*)
                        THEN sum(r.num_stars) END AS stars
            FROM organizations o JOIN repositories r
              ON lower(rtrim(o.github_url, '/')) = 'https://github.com/' || lower(r.owner)
            WHERE EXISTS (SELECT 1 FROM paper_repositories pr JOIN discovery_works w
                          ON w.paper_id=pr.paper_id WHERE pr.repository_id=r.id)
            GROUP BY o.id
        )
        SELECT o.id, coalesce(k.papers,0) AS paper_count, coalesce(k.posts,0) AS post_count,
               coalesce(k.tools,0) AS repository_count, coalesce(s.repos,0) AS owned_repository_count,
               s.stars AS catalog_stars
        FROM organizations o LEFT JOIN kinds k ON k.organization_id=o.id
        LEFT JOIN owned s ON s.id=o.id WHERE o.id = ANY(:ids)
    """),
        {"ids": [int(org.id) for org in organizations]},
    ).mappings()
    metrics = {
        str(row["id"]): {k: v for k, v in row.items() if k != "id"} for row in rows
    }
    return [org.model_copy(update=metrics[org.id]) for org in organizations]
