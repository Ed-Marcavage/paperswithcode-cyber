"""Apply completed repo snapshots atomically to the local discovery catalog."""
import argparse
import json
from pathlib import Path
import re

from sqlalchemy import text

from repository_catalog import ROOT, local_session


def import_snapshots(records, execute):
    updated = 0
    with local_session() as db:
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext('discovery-developers'))"))
        for sql in (ROOT / "backend/database/migrations/add_discovery_developers.sql").read_text().split(";"):
            if sql.strip():
                db.execute(text(sql))
        for row in records:
            if not re.fullmatch(r"[\w.-]+/[\w.-]+", row["full_name"], re.ASCII):
                raise ValueError("Invalid repository path")
            params = {**row, "url": "https://github.com/" + row["catalog_name"]}
            repo_id = db.execute(text("""
                SELECT id FROM repositories r WHERE lower(url) = lower(:url) AND EXISTS (
                    SELECT 1 FROM paper_repositories pr JOIN discovery_works w USING (paper_id)
                    WHERE pr.repository_id = r.id)
            """), params).scalar_one_or_none()
            if repo_id is None:
                continue
            params["repo"] = repo_id
            current = db.execute(text("""
                INSERT INTO discovery_github_repo_snapshots AS s
                    (repository_id, github_repo_id, full_name, observed_at) VALUES
                    (:repo, :github_repo_id, :full_name, :observed_at)
                ON CONFLICT (repository_id) DO UPDATE SET
                    full_name = excluded.full_name, observed_at = excluded.observed_at
                WHERE s.observed_at < excluded.observed_at AND s.github_repo_id = excluded.github_repo_id
                RETURNING repository_id
            """), params).scalar_one_or_none()
            if current is None:
                old_id = db.execute(text("SELECT github_repo_id FROM discovery_github_repo_snapshots WHERE repository_id=:repo"), params).scalar_one()
                if old_id != row["github_repo_id"]:
                    raise ValueError(f"GitHub repository ID changed for {row['catalog_name']}")
                continue
            db.execute(text("DELETE FROM discovery_github_repo_accounts WHERE repository_id=:repo"), params)
            users = row["users"]
            if users:
                values = [dict(u, repo=repo_id, at=row["observed_at"]) for u in users]
                db.execute(text("""
                    INSERT INTO discovery_github_accounts AS a (github_id, login, observed_at) VALUES (:id, :login, :at)
                    ON CONFLICT (github_id) DO UPDATE SET login=excluded.login, observed_at=excluded.observed_at
                    WHERE a.observed_at < excluded.observed_at
                """), values)
                db.execute(text("""
                    INSERT INTO discovery_github_repo_accounts (repository_id, github_id, owns, commits)
                    VALUES (:repo, :id, :owns, :commits)
                """), values)
            updated += 1
        if execute:
            db.commit()
    return updated


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    count = import_snapshots(json.loads(args.snapshot.read_text()), args.execute)
    print(f"{'Updated' if args.execute else 'Previewed'} {count} repositories")
