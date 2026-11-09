"""Metadata/topic import restricted to the isolated pwc_local database.

Preview rolls back schema and data changes. Native papers are reused; reviewed
discovery fields are updated. No model calls, downloads or publication.
Unknown-version arXiv sources retain an external source link, avoiding invented versions.
"""
import argparse
from collections import Counter
import json
from hashlib import sha256
from io import BytesIO
from PIL import Image
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit
from sqlalchemy import text
from backend.database.connection import db_manager
from backend.models.database import Area, Author, Paper, Task, PaperTask, PaperAuthor
from backend.services.author_service import get_or_create_author_by_name, normalize_arxiv_author_name


def source_url(value):
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError(f"Invalid catalog link: {value!r}")
    return value


def discovery_fields(row, names, directory):
    facets = row["facets"]
    for axis, values in facets.items():
        if not isinstance(values, list) or axis not in names or any(v not in names[axis] for v in values):
            raise ValueError(f"Invalid {axis} labels on {row['id']}")
    document = None
    if row.get("text_file"):
        relative = Path(row["text_file"])
        if relative.is_absolute():
            raise ValueError(f"Expected a relative text path on {row['id']}")
        path = (directory / relative).resolve()
        if not path.is_relative_to(directory) or not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError(f"Invalid text file on {row['id']}")
        document = path.read_text(encoding="utf-8")
        if not document.strip() or "\x00" in document:
            raise ValueError(f"Invalid cached text on {row['id']}")
    return dict(catalog_id=row["id"], facets=json.dumps(facets),
                source_url=source_url(row["url"]),
                artifact_url=source_url(row["artifact_url"]) if row.get("artifact_url") else None,
                document_text=document)


def import_preview(db, paper, row, directory):
    if "preview_file" not in row:
        return  # Older bundles contain only metadata and text.
    prefix = f"/api/v1/catalog/papers/{paper.id}/preview/"
    if row["preview_file"] is None:
        db.execute(text("DELETE FROM discovery_previews WHERE paper_id = :id"), {"id": paper.id})
        if (paper.thumbnail_url or "").startswith(prefix):
            paper.thumbnail_url = None
        return
    relative = Path(row["preview_file"])
    path = (directory / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(directory) or not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ValueError(f"Invalid preview path on {row['id']}")
    data = path.read_bytes()
    with Image.open(BytesIO(data)) as image:
        if image.format != "JPEG" or max(image.size) > 640:
            raise ValueError(f"Expected a first-page JPEG on {row['id']}")
        image.load()
    digest = sha256(data).hexdigest()
    db.execute(text("""
        INSERT INTO discovery_previews (paper_id, digest, jpeg) VALUES (:id, :digest, :jpeg)
        ON CONFLICT (paper_id) DO UPDATE SET digest = excluded.digest, jpeg = excluded.jpeg
        WHERE discovery_previews.digest <> excluded.digest
    """), {"id": paper.id, "digest": digest, "jpeg": data})
    paper.thumbnail_url = prefix + digest + ".jpg"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('catalog')
    parser.add_argument('--append', action='store_true', help='Import a reviewed subset while preserving unrelated catalog records')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    catalog = json.loads(Path(args.catalog).read_text())
    db_manager.engine.echo = False
    if catalog['schema_version'] != 1:
        raise ValueError('Unsupported catalog schema')
    if set(catalog["names"]) != {"topic", "target", "contribution", "kind", "year"}:
        raise ValueError("Expected the five discovery vocabulary axes")
    ids = [row['id'] for row in catalog['rows']]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate catalog IDs')
    directory = Path(args.catalog).resolve().parent
    with db_manager.session_local() as db:
        database, user = db.execute(text('SELECT current_database(),current_user')).one()
        if (database, user) != ('pwc_local', 'pwc_local'):
            raise RuntimeError('Refusing any database/user except isolated pwc_local')
        if not args.append and db.query(Paper).count() > len(catalog['rows']):
            raise RuntimeError('Unexpected local catalog contents; inspect before importing')
        db.execute(text("SELECT pg_advisory_xact_lock(27451504)"))
        migration = Path(__file__).resolve().parents[1] / 'backend/database/migrations/add_discovery_catalog.sql'
        for statement in migration.read_text().split(';'):
            if statement.strip():
                db.execute(text(statement))
        for axis, values in catalog['names'].items():
            for value, label in values.items():
                db.execute(text("""
                    INSERT INTO discovery_terms VALUES (:axis, :value, :label)
                    ON CONFLICT (axis, value) DO UPDATE SET label = excluded.label
                    WHERE discovery_terms.label IS DISTINCT FROM excluded.label
                """), dict(axis=axis, value=value, label=label))
        initial_count = db.query(Paper).count()
        area = db.query(Area).filter_by(name='Cybersecurity').one_or_none()
        if area is None:
            area = Area(name='Cybersecurity')
            db.add(area)
            db.flush()
        tasks = {}
        created = linked = unlinked = 0
        mappings = []
        for term, name in catalog['names']['topic'].items():
            slug = 'cyberintel-' + term
            task = db.query(Task).filter(Task.slug == slug).one_or_none()
            if task is None:
                task = Task(name=name, slug=slug, description='Broad research relevance; not demonstrated capability. Imported from the local Cyberintel catalog.', level=0)
                db.add(task)
                db.flush()
            if task.area_id is None:
                task.area_id = area.id
            tasks[term] = task
        task_ids = {key: value.id for key, value in tasks.items()}
        for row in catalog['rows']:
            ax, version = row.get('arxiv_id'), row.get('version')
            as_arxiv = bool(ax and version)
            paper = (db.query(Paper).filter(Paper.arxiv_id == ax, Paper.version == version).one_or_none() if as_arxiv
                     else db.query(Paper).filter(Paper.source_url == row['url']).first())
            if paper is None:
                paper = Paper(title=row['title'], abstract=row['abstract'] or None,
                              source='arxiv' if as_arxiv else 'external',
                              source_url=None if as_arxiv else row['url'],
                              arxiv_id=ax if as_arxiv else None, version=version or 'v1',
                              is_latest_version=True,
                              date_published=date.fromisoformat(row['date'][:10]) if row.get('date') else None)
                db.add(paper)
                db.flush()
                created += 1
            if 'conference_url_pdf' in row:
                if paper.source != 'external':
                    raise ValueError('Publisher PDF field is for curated external records')
                paper.conference_url_pdf = source_url(row['conference_url_pdf'])
            # Keep native topic navigation aligned with the reviewed facet selection.
            desired = [tasks[term].id for term in row['facets']['topic']]
            managed = db.query(Task.id).filter(Task.slug.startswith("cyberintel-"))
            unlinked += db.query(PaperTask).filter(
                PaperTask.paper_id == paper.id, PaperTask.source == 'manual',
                PaperTask.task_id.in_(managed.statement), PaperTask.task_id.notin_(desired),
            ).delete(synchronize_session=False)
            for term in row['facets']['topic']:
                if db.get(PaperTask, (paper.id, tasks[term].id)) is None:
                    db.add(PaperTask(paper_id=paper.id, task_id=tasks[term].id, source='manual'))
                    linked += 1
            byline = [normalize_arxiv_author_name(name) for name in row.get('authors', [])]
            frequencies = Counter(name.casefold() for name in byline)
            for order, name in enumerate(byline, start=1):
                if frequencies[name.casefold()] > 1:
                    # Two people on the same paper may share a display name.
                    # Reuse a verified position on replay, never a global name match.
                    author = (db.query(Author).join(PaperAuthor, Author.id == PaperAuthor.author_id)
                              .filter(PaperAuthor.paper_id == paper.id, PaperAuthor.author_order == order)
                              .one_or_none())
                    if author is None:
                        author = Author(name=name)
                        db.add(author)
                        db.flush()
                    elif author.name != name:
                        raise ValueError(f"Author at reviewed position {order} disagrees on {row['id']}")
                else:
                    author = get_or_create_author_by_name(db, name)
                if db.get(PaperAuthor, (paper.id, author.id)) is None:
                    db.add(PaperAuthor(paper_id=paper.id, author_id=author.id, author_order=order))
            fields = discovery_fields(row, catalog['names'], directory)
            db.execute(text("""
                INSERT INTO discovery_works AS w
                    (paper_id, catalog_id, facets, source_url, artifact_url, document_text)
                VALUES (:paper_id, :catalog_id, CAST(:facets AS jsonb), :source_url, :artifact_url, :document_text)
                ON CONFLICT (paper_id) DO UPDATE SET
                    facets = excluded.facets, source_url = excluded.source_url,
                    artifact_url = excluded.artifact_url, document_text = excluded.document_text
                WHERE w.catalog_id = excluded.catalog_id AND
                    (w.facets, w.source_url, w.artifact_url, w.document_text) IS DISTINCT FROM
                    (excluded.facets, excluded.source_url, excluded.artifact_url, excluded.document_text)
            """), dict(paper_id=paper.id, **fields))
            import_preview(db, paper, row, directory)
            mappings.append({'catalog_id': row['id'], 'paper_id': paper.id, 'source': paper.source})
        db.flush()
        expected = {(m["catalog_id"], m["paper_id"]) for m in mappings}
        actual = set(db.execute(text("SELECT catalog_id, paper_id FROM discovery_works")))
        if (not expected.issubset(actual)) or (not args.append and actual != expected):
            raise RuntimeError('Catalog ID mapped to a different native paper')
        total = db.query(Paper).count()
        if total != (initial_count + created if args.append else len(catalog['rows'])):
            raise RuntimeError('Import would create unexpected duplicate records')
        if args.execute:
            db.commit()
        else:
            db.rollback()
    print(json.dumps({'executed': args.execute, 'new_papers': created, 'new_task_links': linked,
                      'removed_task_links': unlinked, 'total_catalog_records': total, 'tasks': task_ids, 'papers': mappings}))


if __name__ == '__main__':
    main()
