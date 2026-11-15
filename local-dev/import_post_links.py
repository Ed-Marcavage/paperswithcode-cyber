"""Link industry posts to their publisher organization and to the repositories their review cites.

Inputs: one or more JSON objects keyed by catalog ID, each review carrying `code_links`
([{url, role, evidence}], as written by the industry-intake export and merge step,
bundle/v2-fields.json), and backend/config/publisher_organizations.json.

1. Publisher. Every post in the catalog whose URL host is in the mapping file is linked
   to that organization with role `publisher` (source `publisher_host`). An organization
   with the same name (case-insensitive) or a website on a mapped host is reused;
   otherwise one is created, featured like import_catalog_organizations.py does. A
   `publisher_host` link the mapping no longer gives is removed. Links from reviewed
   organization manifests are kept; one to the same organization gains role `publisher`.
2. Repositories. Each code link with a role in IMPORTED_ROLES that names a GitHub
   repository resolves to one repository record (owner/name compared case-insensitively,
   see github_repository in backend/utils/github_utils.py; created with source `cyberintel-local` when
   new) and to one link per post and repository with role, evidence and the cited URL
   (source `post-review`). A post citing one repository under several roles keeps the
   first role in IMPORTED_ROLES order. A repository GitHub knows under a new name (renamed
   or transferred, per the developer snapshots) resolves to the record with its current
   name. The record under the old name stays, without links, and keeps that knowledge
   (its snapshot) for later runs; a name first seen before its snapshot exists resolves
   on the run after fetch_developers.py/import_developers.py. `is_official` is set for CREDITED_ROLES only: that
   flag is what star-based Trending and the Developers tab count. `post-review` links the
   input explicitly replaces are removed; omitted posts and missing `code_links` fields
   are untouched. An explicit empty list clears that post's `post-review` links.
   Links from reviewed repository manifests are kept
   (their empty role/evidence is filled in).

Stars and developers follow with fetch_developers.py and import_developers.py, which
collect credited repositories only. Preview rolls back; pass --execute to commit. A rerun
with the same inputs changes nothing. --replace-all requires an explicit code_links
list for every catalog post; incomplete input is refused before changing links.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re

from sqlalchemy import text

from backend.database.connection import db_manager
from backend.models.database import Organization, PaperOrganization, PaperRepository, Repository
from backend.services import publishers
from backend.utils.github_utils import canonical_repository_url, github_repository, repository_key

# The one setting for which repository links credit the repository to the post:
# only these roles create developers and count toward star-based Trending.
CREDITED_ROLES = frozenset({"original"})
# Roles imported as links, strongest first. `unclear` and `navigation` stay in the export only.
IMPORTED_ROLES = ("original", "target", "supporting", "dependency")
DROPPED_ROLES = frozenset({"unclear", "navigation"})
PUBLISHER_SOURCE = "publisher_host"
LINK_SOURCE = "post-review"


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")[:100]


def desired_links(code_links, where):
    """Repository key -> (owner, name, role, evidence, url) for one post, plus what was skipped."""
    chosen, skipped = {}, Counter()
    for link in code_links:
        role = link.get("role")
        if role in DROPPED_ROLES:
            skipped[f"role_{role}"] += 1
            continue
        if role not in IMPORTED_ROLES:
            raise ValueError(f"Unknown code link role {role!r} on {where}")
        found = github_repository(link.get("url"))
        if found is None:
            skipped["not_a_github_repository"] += 1
            continue
        key = repository_key(link["url"])
        evidence = (link.get("evidence") or "").strip() or None
        candidate = (found[0], found[1], role, evidence, link["url"])
        if key in chosen:
            skipped["same_repository_again"] += 1
            if IMPORTED_ROLES.index(role) >= IMPORTED_ROLES.index(chosen[key][2]):
                continue
        chosen[key] = candidate
    return chosen, skipped


def resolve_organizations(db, counts):
    """Mapping-file organization name -> organization id, creating missing records."""
    entries = publishers.load_organizations()
    table = {host: entry["name"] for entry in entries for host in entry["hosts"]}
    existing = db.query(Organization).all()
    by_name = {org.name.casefold(): org for org in existing}
    by_domain = {}
    for org in existing:
        mapped = publishers.organization_for_url(org.website_url, table)
        if mapped:
            by_domain.setdefault(mapped, org)
    slugs = {org.slug for org in existing}
    ids = {}
    for entry in entries:
        name = entry["name"].strip()
        org = by_name.get(name.casefold()) or by_domain.get(name)
        if org is None:
            slug = slugify(name)
            if not slug or slug in slugs:
                raise ValueError(f"Cannot derive a free slug for organization {name!r}")
            org = Organization(name=name, slug=slug, website_url=entry["website_url"], is_featured=True)
            db.add(org)
            db.flush()
            slugs.add(slug)
            counts["organizations_created"] += 1
        else:
            counts["organizations_reused"] += 1
        ids[name] = org.id
    return ids, table


def reviewed_posts(posts, reviews, *, replace_all=False):
    """Missing data is not an instruction to delete. Validate before any writes."""
    selected = []
    for post in posts:
        review = reviews.get(post[1])
        if review is None or "code_links" not in review:
            if replace_all:
                raise ValueError(f"Full replacement requires code_links for every post; missing {post[1]}")
            continue
        if not isinstance(review["code_links"], list):
            raise ValueError(f"code_links must be an explicit list on {post[1]}")
        desired_links(review["code_links"], post[1])
        selected.append(post)
    return selected


def changed_post(counts, paper_id):
    counts.setdefault("changed_post_ids", set()).add(paper_id)


def link_publishers(db, posts, counts):
    org_ids, table = resolve_organizations(db, counts)
    links = {}
    for link in db.query(PaperOrganization).filter(PaperOrganization.paper_id.in_([p for p, _, _ in posts])):
        links.setdefault(link.paper_id, []).append(link)
    unmapped = Counter()
    for paper_id, _, url in posts:
        name = publishers.organization_for_url(url, table)
        org_id = org_ids.get(name)
        if org_id is None:
            unmapped[publishers.host(url)] += 1
        current = links.get(paper_id, [])
        for link in current:
            if link.source == PUBLISHER_SOURCE and link.organization_id != org_id:
                db.delete(link)
                counts["publisher_links_removed"] += 1
                changed_post(counts, paper_id)
        if org_id is None:
            continue
        same = next((link for link in current if link.organization_id == org_id), None)
        if same is None:
            db.add(PaperOrganization(paper_id=paper_id, organization_id=org_id,
                                     source=PUBLISHER_SOURCE, role="publisher"))
            counts["publisher_links_added"] += 1
            changed_post(counts, paper_id)
        elif same.role is None:
            same.role = "publisher"
            counts["publisher_links_updated"] += 1
            changed_post(counts, paper_id)
    counts["posts_without_publisher"] = sum(unmapped.values())
    counts["unmapped_hosts"] = dict(unmapped)


def known_repositories(db, counts):
    """Repository key -> record, and the ids of records superseded by another name.

    A GitHub repository known under several names (renamed or transferred, as the
    developer snapshots show) resolves to the record carrying its current name, so
    every name a post uses lands on one record."""
    repositories = {}
    for repo in db.query(Repository).order_by(Repository.id):
        key = repository_key(repo.url)
        if key:
            repositories.setdefault(key, repo)
    if db.scalar(text("SELECT to_regclass('discovery_github_repo_snapshots')")) is None:
        return repositories, set()
    groups = {}
    for repository_id, github_repo_id, full_name in db.execute(text(
            "SELECT repository_id, github_repo_id, full_name FROM discovery_github_repo_snapshots")):
        groups.setdefault(github_repo_id, []).append((repository_id, full_name))
    by_id = {repo.id: repo for repo in repositories.values()}
    aliases = set()
    for members in groups.values():
        current = repository_key(canonical_repository_url(*members[0][1].split("/", 1)))
        records = [by_id[repository_id] for repository_id, _ in members if repository_id in by_id]
        if not records:
            continue
        canonical = next((r for r in records if repository_key(r.url) == current), min(records, key=lambda r: r.id))
        repositories[current] = canonical
        for record in records:
            repositories[repository_key(record.url)] = canonical
            if record.id != canonical.id:
                aliases.add(record.id)
    counts["repositories_known_under_two_names"] = len(aliases)
    return repositories, aliases


def link_repositories(db, posts, reviews, counts):
    posts = reviewed_posts(posts, reviews)
    repositories, _ = known_repositories(db, counts)
    links = {}
    for link in db.query(PaperRepository).filter(PaperRepository.paper_id.in_([p for p, _, _ in posts])):
        links.setdefault(link.paper_id, {})[link.repository_id] = link
    skipped = Counter()
    for paper_id, catalog_id, _ in posts:
        chosen, skipped_here = desired_links(reviews[catalog_id]["code_links"], catalog_id)
        skipped.update(skipped_here)
        current = links.get(paper_id, {})
        wanted = {}  # repository id -> link values; the strongest role when two names meet
        for key, (owner, name, role, evidence, url) in chosen.items():
            repo = repositories.get(key)
            if repo is None:
                repo = Repository(url=canonical_repository_url(owner, name), owner=owner, name=name, source="cyberintel-local")
                db.add(repo)
                db.flush()
                repositories[key] = repo
                counts["repositories_created"] += 1
            values = dict(role=role, evidence=evidence, link_url=url, is_official=role in CREDITED_ROLES)
            if repo.id in wanted and IMPORTED_ROLES.index(role) >= IMPORTED_ROLES.index(wanted[repo.id]["role"]):
                continue
            wanted[repo.id] = values
        for repo_id, values in wanted.items():
            link = current.get(repo_id)
            if link is None:
                db.add(PaperRepository(paper_id=paper_id, repository_id=repo_id, source=LINK_SOURCE, **values))
                counts["repository_links_added"] += 1
                changed_post(counts, paper_id)
            elif link.source == LINK_SOURCE:
                changed = {k: v for k, v in values.items() if getattr(link, k) != v}
                for k, v in changed.items():
                    setattr(link, k, v)
                counts["repository_links_updated"] += bool(changed)
                if changed:
                    changed_post(counts, paper_id)
            else:  # From a reviewed manifest: keep it, fill in what it lacks.
                filled = {k: values[k] for k in ("role", "evidence", "link_url") if getattr(link, k) is None}
                for k, v in filled.items():
                    setattr(link, k, v)
                counts["manifest_links_filled"] += bool(filled)
                if filled:
                    changed_post(counts, paper_id)
        for repo_id, link in current.items():
            if link.source == LINK_SOURCE and repo_id not in wanted:
                db.delete(link)
                counts["repository_links_removed"] += 1
                changed_post(counts, paper_id)
    counts["code_links_skipped"] = dict(skipped)


def local_session():
    db_manager.engine.echo = False
    db = db_manager.session_local()
    if tuple(db.execute(text("SELECT current_database(), current_user")).one()) != ("pwc_local", "pwc_local"):
        db.close()
        raise RuntimeError("Refusing any database/user except isolated pwc_local")
    return db


def import_links(db, reviews, *, replace_all=False) -> dict:
    """Apply the links in the open transaction; the caller commits or rolls back."""
    db.execute(text("SELECT pg_advisory_xact_lock(27451504)"))
    migration = Path(__file__).resolve().parents[1] / "backend/database/migrations/add_discovery_post_links.sql"
    for statement in migration.read_text().split(";"):
        if statement.strip():
            db.execute(text(statement))
    posts = db.execute(text("""
        SELECT paper_id, catalog_id, source_url FROM discovery_works
         WHERE facets -> 'kind' ? 'post' ORDER BY paper_id
    """)).all()
    counts = Counter()
    selected = reviewed_posts(posts, reviews, replace_all=replace_all)
    link_publishers(db, selected, counts)
    link_repositories(db, selected, reviews, counts)
    counts["posts_changed"] = len(counts.get("changed_post_ids", set()))
    counts["links_added"] = counts["publisher_links_added"] + counts["repository_links_added"]
    counts["links_removed"] = counts["publisher_links_removed"] + counts["repository_links_removed"]
    db.flush()
    totals = db.execute(text("""
        SELECT coalesce(pr.role, 'none'), count(*), count(DISTINCT pr.repository_id)
          FROM paper_repositories pr JOIN discovery_works w USING (paper_id)
         WHERE w.facets -> 'kind' ? 'post' GROUP BY 1 ORDER BY 1
    """)).all()
    return {
        "posts": len(posts), "reviews": len(reviews), "posts_skipped": len(posts) - len(selected),
        "reviews_without_post": len(reviews.keys() - {c for _, c, _ in posts}),
        **{k: counts[k] for k in CHANGE_COUNTS + (
            "organizations_reused", "posts_without_publisher", "repositories_known_under_two_names")},
        "unmapped_hosts": counts["unmapped_hosts"], "code_links_skipped": counts["code_links_skipped"],
        "post_links_by_role": {role: {"links": n, "repositories": r} for role, n, r in totals},
    }


# Counts that are zero when a rerun changes nothing.
CHANGE_COUNTS = ("posts_changed", "links_added", "links_removed", "organizations_created", "publisher_links_added", "publisher_links_updated",
                 "publisher_links_removed", "repositories_created", "repository_links_added",
                 "repository_links_updated", "repository_links_removed", "manifest_links_filled")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("fields", type=Path, nargs="+")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--replace-all", action="store_true", help="Require explicit code_links for every catalog post")
    args = parser.parse_args()
    reviews = {}
    for path in args.fields:
        document = json.loads(path.read_text())
        repeated = sorted(reviews.keys() & document.keys())
        if repeated:
            raise ValueError(f"Catalog IDs repeated across input files: {repeated[:5]}")
        reviews.update(document)
    with local_session() as db:
        result = import_links(db, reviews, replace_all=args.replace_all)
        if args.execute:
            db.commit()
        else:
            db.rollback()
    print(json.dumps({"executed": args.execute, **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
