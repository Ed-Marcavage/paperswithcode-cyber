"""Package reviewed catalog rows and explicitly selected sources. No network or DB writes."""
from contextlib import closing
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sqlite3
import tempfile

FIELDS = ("id", "title", "abstract", "url", "authors", "date", "year", "kind",
          "facets", "arxiv_id", "version", "artifact_url", "conference_url_pdf")


def load(path):
    return json.loads(path.read_text(encoding="utf-8")) if path else {}


def render_preview(key, item, base, roots, stage):
    source = item.get("files", {}).get("pdf")
    if not source:
        return None
    pdf = (base / source).resolve(strict=True)
    if not pdf.is_file() or not any(pdf.is_relative_to(root) for root in roots):
        raise ValueError(f"Invalid PDF path for {key}")
    if item.get("pdf_sha256"):
        with pdf.open("rb") as stream:
            digest = hashlib.sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != item["pdf_sha256"]:
            raise ValueError(f"PDF checksum mismatch for {key}")
    stem = "previews/" + hashlib.sha256(key.encode()).hexdigest()
    subprocess.run(
        ["pdftoppm", "-f", "1", "-l", "1", "-singlefile", "-scale-to", "640",
         "-jpeg", str(pdf), str(stage / stem)], check=True, timeout=60,
    )
    return stem + ".jpg"


def extract(args):
    catalog, documents, artifacts = map(load, (args.catalog, args.documents, args.artifacts))
    ids = {row["id"] for row in catalog["rows"]}
    explicit = set(args.v2_text_for)
    if catalog["schema_version"] != 1 or len(ids) != len(catalog["rows"]):
        raise ValueError("Expected unique reviewed rows in a schema version 1 catalog")
    if (documents.keys() | artifacts.keys() | explicit) - ids:
        raise ValueError("Input references papers outside the reviewed catalog")
    if explicit and not (args.v2_db and args.v2_root):
        raise ValueError("--v2-text-for requires --v2-db and --v2-root")
    if args.output.exists():
        raise FileExistsError("Use a new output directory")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    roots = [p.resolve(strict=True) for p in args.text_root]
    pdf_roots = [p.resolve(strict=True) for p in args.pdf_root]
    with tempfile.TemporaryDirectory(dir=args.output.parent) as tmp:
        stage = Path(tmp) / "bundle"
        (stage / "text").mkdir(parents=True)
        if pdf_roots:
            (stage / "previews").mkdir()
        rows = []
        for row in catalog["rows"]:
            key = row["id"]
            clean = {k: row[k] for k in FIELDS if k in row}
            if key in artifacts:
                clean["artifact_url"] = artifacts[key]
            item = documents.get(key, {})
            source = item.get("files", {}).get("text")
            base = args.documents.parent if args.documents else args.catalog.parent
            if pdf_roots:
                clean["preview_file"] = render_preview(key, item, base, pdf_roots, stage)
            if key in explicit:
                if source:
                    raise ValueError(f"{key} has two text sources; select only one")
                uri = args.v2_db.resolve(strict=True).as_uri() + "?mode=ro"
                with closing(sqlite3.connect(uri, uri=True)) as db:
                    record = db.execute(
                        "SELECT fulltext_path FROM work WHERE id = ? OR (arxiv_id IS NOT NULL AND arxiv_id = ?)",
                        (key, row.get("arxiv_id")),
                    ).fetchall()
                if len(record) != 1 or not record[0][0]:
                    raise ValueError(f"No unique cached v2 document for {key}")
                source, base = record[0][0], args.v2_root.resolve(strict=True)
            if source:
                path = (base / source).resolve(strict=True)
                if not any(path.is_relative_to(root) for root in roots) or not path.is_file():
                    raise ValueError(f"Document for {key} is outside the selected text roots")
                if path.stat().st_size > 4 * 1024 * 1024:
                    raise ValueError(f"Document for {key} exceeds the 4 MiB limit")
                raw = path.read_bytes()
                if item.get("text_sha256") and hashlib.sha256(raw).hexdigest() != item["text_sha256"]:
                    raise ValueError(f"Cached document checksum mismatch for {key}")
                doc = raw.decode("utf-8")
                if not doc.strip() or "\x00" in doc:
                    raise ValueError(f"Document for {key} is not usable UTF-8 text")
                filename = "text/" + hashlib.sha256(key.encode()).hexdigest() + ".txt"
                (stage / filename).write_bytes(raw)
                clean["text_file"] = filename
            rows.append(clean)
        (stage / "catalog.json").write_text(json.dumps({
            "schema_version": 1, "names": catalog["names"], "rows": rows,
        }, ensure_ascii=False) + "\n", encoding="utf-8")
        stage.rename(args.output)
    print(f"Packaged {len(rows)} reviewed records; {sum('text_file' in row for row in rows)} documents.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", type=Path, help="Schema version 1 reviewed vocabulary and rows")
    parser.add_argument("output", type=Path, help="New directory for the portable bundle")
    parser.add_argument("--documents", type=Path, help="Reviewed document index keyed by catalog ID")
    parser.add_argument("--artifacts", type=Path, help="JSON mapping of catalog IDs to precise artifact URLs")
    parser.add_argument("--text-root", action="append", type=Path, default=[], help="Allowed input document directory (repeatable)")
    parser.add_argument("--pdf-root", action="append", type=Path, default=[],
                        help="Render first-page previews from indexed PDFs under this directory (repeatable)")
    parser.add_argument("--v2-db", type=Path, help="Read-only v2 knowledge database with work.fulltext_path")
    parser.add_argument("--v2-root", type=Path, help="Corpus root for relative v2 document paths")
    parser.add_argument("--v2-text-for", action="append", default=[], metavar="CATALOG_ID",
                        help="Read this reviewed record's cached v2 text (repeatable)")
    extract(parser.parse_args())
