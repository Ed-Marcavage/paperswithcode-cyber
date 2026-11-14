"""Apply reviewed organization profiles and work links to the local catalog."""

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit
from sqlalchemy import text
from backend.models.database import Organization, PaperOrganization
from backend.database.connection import db_manager


def load(manifest, execute):
    db_manager.engine.echo = False
    with db_manager.session_local() as db:
        if tuple(db.execute(text("SELECT current_database(), current_user")).one()) != (
            "pwc_local",
            "pwc_local",
        ):
            raise RuntimeError("Organization seed requires the local catalog database")
        db.execute(text("SELECT pg_advisory_xact_lock(27451504)"))
        migration = Path(__file__).resolve().parents[1] / "backend/database/migrations/add_discovery_post_links.sql"
        for statement in migration.read_text().split(";"):
            if statement.strip():
                db.execute(text(statement))
        for row in manifest:
            org = db.query(Organization).filter_by(slug=row["slug"]).one_or_none()
            if org is None:
                org = Organization(slug=row["slug"])
                db.add(org)
            for field in ("name", "website_url", "github_url", "description"):
                setattr(org, field, row.get(field))
            if row.get("github_account_id"):
                org.logo_url = f"https://avatars.githubusercontent.com/u/{int(row['github_account_id'])}?s=96"
            org.is_featured = True
            db.flush()
            for link in row["works"]:
                if (
                    link["role"]
                    not in {"publisher", "research affiliation", "repository owner"}
                    or urlsplit(link["evidence"]).scheme != "https"
                ):
                    raise ValueError(f"Missing attribution evidence for {link['id']}")
                paper_id = db.execute(
                    text("SELECT paper_id FROM discovery_works WHERE catalog_id=:id"),
                    {"id": link["id"]},
                ).scalar_one()
                existing = db.get(PaperOrganization, (paper_id, org.id))
                if existing is None:
                    db.add(
                        PaperOrganization(
                            paper_id=paper_id,
                            organization_id=org.id,
                            source="manual",
                            role=link["role"],
                        )
                    )
                elif existing.role is None:
                    existing.role = link["role"]
        db.flush()
        if execute:
            db.commit()
        else:
            db.rollback()
    print(
        f"{'Applied' if execute else 'Previewed'} {len(manifest)} organization profiles"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    load(json.loads(args.manifest.read_text()), args.execute)
