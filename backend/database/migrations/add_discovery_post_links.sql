-- Reviewed links from catalog works (papers and industry posts) to repositories and organizations.
-- Additive and idempotent. Loaders apply it before writing: local-dev/import_post_links.py,
-- local-dev/import_developers.py and local-dev/import_catalog_organizations.py.
-- Statements are split on semicolons, so keep them out of comments.

-- How a work relates to a repository, as reviewed: original (the work's own code),
-- target (the code the work studies or attacks), supporting, dependency.
-- evidence is the review's sentence, link_url the exact link the work cites (may be a sub-path).
-- source names the loader that owns the link (post-review), NULL for older reviewed manifests.
-- is_official stays the switch that credits a repository to the work: star-based
-- Trending and the Developers tab count only is_official links. import_post_links.py
-- sets it from the role (CREDITED_ROLES there).
ALTER TABLE paper_repositories ADD COLUMN IF NOT EXISTS role text;
ALTER TABLE paper_repositories ADD COLUMN IF NOT EXISTS evidence text;
ALTER TABLE paper_repositories ADD COLUMN IF NOT EXISTS link_url text;
ALTER TABLE paper_repositories ADD COLUMN IF NOT EXISTS source text;

-- Links from the reviewed repository manifests were official code: role original.
UPDATE paper_repositories SET role = 'original' WHERE role IS NULL AND is_official AND source IS NULL;

CREATE INDEX IF NOT EXISTS idx_paper_repositories_repository_role
    ON paper_repositories (repository_id, role);

-- How a work relates to an organization: publisher, research affiliation or repository owner.
-- import_post_links.py writes publisher links (source publisher_host) from
-- backend/config/publisher_organizations.json.
ALTER TABLE paper_organizations ADD COLUMN IF NOT EXISTS role text;
