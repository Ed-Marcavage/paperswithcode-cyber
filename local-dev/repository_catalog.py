"""Import reviewed repository associations and refresh local GitHub star snapshots.

Only pwc_local is permitted. No repo code is downloaded or executed. Historical
date-only counts are deliberately excluded: they cannot establish hourly growth.
The upstream EMA calculator owns ranking, including its zero-score cold start.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / '.github/workflows'))


def validate_snapshot(record, now=None):
    now = now or datetime.now(timezone.utc)
    name = record['full_name']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', name):
        raise ValueError('Invalid GitHub repository name')
    if record['url'].lower() != ('https://github.com/' + name).lower():
        raise ValueError('Repository URL does not match canonical name')
    if type(record['stars']) is not int or record['stars'] < 0:
        raise ValueError('Invalid star count')
    observed = datetime.fromisoformat(record['observed_at'].replace('Z', '+00:00'))
    if observed.tzinfo is None or not timedelta(0) <= now - observed <= timedelta(hours=24):
        raise ValueError('Snapshot must have a precise timezone and be at most 24 hours old')
    return observed


def local_session():
    from backend.database.connection import db_manager
    from sqlalchemy import text
    db_manager.engine.echo = False
    db = db_manager.session_local()
    if tuple(db.execute(text('SELECT current_database(), current_user')).one()) != ('pwc_local', 'pwc_local'):
        db.close()
        raise RuntimeError('Refusing any database/user except isolated pwc_local')
    return db


def score(db, ids):
    if not ids:
        return {'updated': 0, 'insufficient': 0, 'skipped': 0}
    path = ROOT / '.github/workflows/scripts/hourly/calculate_trending_scores.py'
    spec = importlib.util.spec_from_file_location('upstream_trending', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.process_repository_batch(db, ids)


def store_snapshot(db, repo, record):
    from backend.models.database import RepositoryStarHistory
    observed = validate_snapshot(record)
    latest = db.query(RepositoryStarHistory).filter_by(repository_id=repo.id).order_by(RepositoryStarHistory.snapshot_at.desc()).first()
    if latest and observed <= latest.snapshot_at:
        return False
    repo.num_stars = record['stars']
    repo.num_stars_updated_at = observed
    repo.source = 'cyberintel-local-archived' if record['archived'] else 'cyberintel-local'
    db.add(RepositoryStarHistory(repository_id=repo.id, num_stars=record['stars'], snapshot_at=observed))
    return True


def import_repositories(manifest, execute=False):
    from sqlalchemy import func, or_
    from backend.models.database import Paper, Repository, PaperRepository
    records = manifest['repositories']
    if not 1 <= len(records) <= 30:
        raise ValueError('This local batch is bounded to 30 repositories')
    for record in records:
        validate_snapshot(record)
        if not record.get('links') or any(not link.get('evidence_url') or not link.get('evidence_note') or type(link.get('is_official')) is not bool for link in record['links']):
            raise ValueError('Every association requires reviewed primary-source evidence')
    with local_session() as db:
        counts = {'new_repositories': 0, 'new_links': 0, 'new_snapshots': 0}
        changed = []
        for record in records:
            repo = db.query(Repository).filter(func.lower(Repository.url) == record['url'].lower()).one_or_none()
            if repo is None:
                owner, name = record['full_name'].split('/')
                repo = Repository(url=record['url'], owner=owner, name=name, source='cyberintel-local')
                db.add(repo)
                db.flush()
                counts['new_repositories'] += 1
            elif repo.source not in ('cyberintel-local', 'cyberintel-local-archived'):
                raise ValueError('Repository belongs to another importer; review before changing it')
            for link in record['links']:
                predicates = [Paper.source_url == link['paper_url']]
                if link.get('arxiv_id'):
                    predicates.append(Paper.arxiv_id == link['arxiv_id'])
                paper = db.query(Paper).filter(or_(*predicates), Paper.is_latest_version).one()
                old = db.get(PaperRepository, (paper.id, repo.id))
                if old is None:
                    db.add(PaperRepository(paper_id=paper.id, repository_id=repo.id, is_official=link['is_official']))
                    counts['new_links'] += 1
                elif old.is_official != link['is_official']:
                    raise ValueError('Existing association disagrees with reviewed manifest')
            if store_snapshot(db, repo, record):
                counts['new_snapshots'] += 1
                changed.append(repo.id)
        db.flush()
        if execute:
            # Upstream calculator commits this transaction, including the snapshots.
            counts['scores'] = score(db, changed)
            db.commit()
        else:
            db.rollback()
        return {'executed': execute, **counts}


def fetch_repository(full_name):
    request = Request('https://api.github.com/repos/' + full_name, headers={
        'Accept': 'application/vnd.github+json', 'User-Agent': 'Cyberintel-local-catalog/1'})
    with urlopen(request, timeout=20) as response:
        data = json.load(response)
    if data['full_name'].lower() != full_name.lower() or data.get('private'):
        raise ValueError('Repository identity changed or is no longer public; review manually')
    record = {'full_name': data['full_name'], 'url': data['html_url'],
              'stars': data['stargazers_count'], 'archived': data['archived'],
              'observed_at': datetime.now(timezone.utc).isoformat()}
    validate_snapshot(record)
    return record


def refresh():
    from sqlalchemy import text
    with local_session() as db:
        # Keep concurrent CLI and scheduled runs from spending the budget twice.
        locked = db.execute(text("SELECT pg_try_advisory_xact_lock(hashtext('pwc_catalog_star_refresh'))")).scalar_one()
        if not locked:
            return {'refreshed': 0, 'errors': [], 'skipped': 'refresh already running'}
        result = refresh_due(db)
        # Upstream stores one rolling observation per organization per UTC day.
        from backend.services.organization_trending_service import OrganizationTrendingService
        result["organizations"] = OrganizationTrendingService(db).calculate()
        return result


def refresh_due(db):
    from sqlalchemy import or_
    from backend.models.database import Repository
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=55)
    managed = db.query(Repository.id, Repository.owner, Repository.name).filter(
        Repository.source.in_(('cyberintel-local', 'cyberintel-local-archived')))
    updated = Repository.num_stars_updated_at
    not_due = managed.filter(updated > cutoff).count()
    due = managed.filter(or_(updated.is_(None), updated <= cutoff))
    pending = due.count()
    batch = due.order_by(updated.asc().nulls_first(), Repository.id).limit(30).all()
    changed, errors, attempted = 0, [], 0
    for id, owner, repository in batch:
        name = f'{owner}/{repository}'
        attempted += 1
        try:
            record = fetch_repository(name)
        except (HTTPError, URLError, TimeoutError, ValueError, KeyError) as exc:
            errors.append({'repository': name, 'error': str(exc)})
            if isinstance(exc, HTTPError) and exc.code in (403, 429):
                break  # Respect the shared anonymous API budget; retry next cycle.
            continue
        with local_session() as writer:
            repo = writer.get(Repository, id, with_for_update=True)
            if repo and store_snapshot(writer, repo, record):
                writer.flush()
                score(writer, [id])
                changed += 1
            writer.commit()
    return {'refreshed': changed, 'not_due': not_due, 'deferred': max(0, pending - attempted), 'errors': errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', nargs='?')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--refresh', action='store_true')
    parser.add_argument('--loop', action='store_true')
    parser.add_argument('--fetch-current', action='store_true', help='Replace saved counts with fresh public GitHub observations before importing')
    args = parser.parse_args()
    if args.refresh:
        if not args.execute or args.manifest or args.fetch_current:
            parser.error('--refresh requires --execute and no manifest')
        while True:
            print(json.dumps({'at': datetime.now(timezone.utc).isoformat(), **refresh()}), flush=True)
            if not args.loop:
                break
            time.sleep(3600)
    else:
        if not args.manifest or args.loop:
            parser.error('Provide a manifest; --loop is only supported with --refresh')
        manifest = json.loads(Path(args.manifest).read_text())
        if args.fetch_current:
            if not 1 <= len(manifest['repositories']) <= 30:
                parser.error('Manifest must contain 1–30 repositories')
            for row in manifest['repositories']:
                # Validate the name/URL before using it in a public API request.
                validate_snapshot({**row, 'observed_at': datetime.now(timezone.utc).isoformat()})
                row.update(fetch_repository(row['full_name']))
        print(json.dumps(import_repositories(manifest, args.execute)))


if __name__ == '__main__':
    main()
