CREATE TABLE IF NOT EXISTS discovery_github_accounts (
    github_id bigint PRIMARY KEY,
    login text NOT NULL,
    observed_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS discovery_github_repo_snapshots (
    repository_id bigint PRIMARY KEY REFERENCES repositories(id) ON DELETE CASCADE,
    github_repo_id bigint NOT NULL,
    full_name text NOT NULL,
    observed_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS discovery_github_repo_accounts (
    repository_id bigint NOT NULL REFERENCES discovery_github_repo_snapshots(repository_id) ON DELETE CASCADE,
    github_id bigint NOT NULL REFERENCES discovery_github_accounts(github_id),
    owns boolean NOT NULL,
    commits integer NOT NULL CHECK (commits >= 0),
    PRIMARY KEY (repository_id, github_id),
    CHECK (owns OR commits > 0)
);

CREATE INDEX IF NOT EXISTS ix_discovery_repo_accounts_github_id
    ON discovery_github_repo_accounts (github_id);

CREATE OR REPLACE VIEW discovery_developer_work AS
WITH tracked AS (
    SELECT DISTINCT ON (s.github_repo_id) s.*
    FROM discovery_github_repo_snapshots s
    WHERE EXISTS (
        SELECT 1 FROM paper_repositories pr JOIN discovery_works w USING (paper_id)
        WHERE pr.repository_id = s.repository_id
    )
    ORDER BY s.github_repo_id, s.observed_at DESC, s.repository_id
)
SELECT a.github_id, a.login, s.github_repo_id, s.full_name, e.owns, e.commits
FROM tracked s JOIN discovery_github_repo_accounts e USING (repository_id)
JOIN discovery_github_accounts a USING (github_id);
