"""Loading refreshed post previews: manifest checks, planning and the dry run, with a fake session."""
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

import load_post_previews as loader

URL = "https://example.com/post"


def jpeg(colour="white", size=(400, 550)):
    buffer = BytesIO()
    Image.new("RGB", size, colour).save(buffer, "JPEG", quality=85)
    return buffer.getvalue()


def entry(data=b"", **fields):
    return {"item": "7", "paper_id": 7, "url": URL, "file": "7.jpg", "digest": sha256(data).hexdigest(),
            "method": "screenshot", "jpeg": data, **fields}


def current(**fields):
    return {"paper_id": 7, "source_url": URL, "thumbnail_url": None, "digest": None, **fields}


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def one(self):
        return self.rows[0]

    def mappings(self):
        return self.rows


class FakeSession:
    def __init__(self, matches, database=("pwc_local", "pwc_local")):
        self.matches = matches
        self.database = database
        self.statements = []

    def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.statements.append(sql)
        if sql.startswith("SELECT current_database()"):
            return FakeResult([self.database])
        if sql.startswith("SELECT w.paper_id"):
            return FakeResult(self.matches)
        return FakeResult([])

    def writes(self):
        return [s for s in self.statements if s.startswith(("INSERT", "UPDATE", "DELETE"))]


class ReadManifestTest(unittest.TestCase):
    def write(self, directory, data, **fields):
        path = Path(directory)
        (path / "7.jpg").write_bytes(data)
        post = {key: value for key, value in entry(data, **fields).items() if key != "jpeg"}
        (path / "manifest.json").write_text(json.dumps({"version": 1, "posts": [post]}))
        return path / "manifest.json"

    def test_reads_matching_files(self):
        with tempfile.TemporaryDirectory() as directory:
            data = jpeg()
            entries = loader.read_manifest(self.write(directory, data))
            self.assertEqual(entries[0]["jpeg"], data)

    def test_rejects_a_digest_mismatch_wrong_size_or_escaping_path(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "digest"):
                loader.read_manifest(self.write(directory, jpeg(), digest="0" * 64))
            with self.assertRaisesRegex(ValueError, "400x550"):
                loader.read_manifest(self.write(directory, jpeg(size=(400, 400))))
            with self.assertRaisesRegex(ValueError, "invalid preview file"):
                loader.read_manifest(self.write(directory, jpeg(), file="../7.jpg"))


class PlanTest(unittest.TestCase):
    def test_insert_update_unchanged(self):
        new = entry(b"new")
        target = loader.preview_url(7, new["digest"])
        self.assertEqual(loader.plan(new, [current()])["action"], "insert")
        self.assertEqual(loader.plan(new, [current()])["thumbnail_url"], target)
        old = current(digest="old", thumbnail_url=loader.preview_url(7, "old"))
        self.assertEqual(loader.plan(new, [old])["action"], "update")
        same = current(digest=new["digest"], thumbnail_url=target)
        self.assertEqual(loader.plan(new, [same])["action"], "unchanged")

    def test_skips(self):
        new = entry(b"new")
        cases = {
            "not a post in this catalog": [],
            "several posts share this URL": [current(), current(paper_id=8)],
            "catalog URL differs from the manifest": [current(source_url="https://example.com/other")],
            "thumbnail set by another source": [current(thumbnail_url="https://cdn.example.com/x.jpg")],
        }
        for reason, matches in cases.items():
            with self.subTest(reason=reason):
                self.assertEqual(loader.plan(new, matches), {**loader.plan(new, matches), "action": "skip",
                                                             "reason": reason})

    def test_url_entry_takes_the_catalog_paper_id(self):
        step = loader.plan(entry(b"new", paper_id=None, item=URL), [current(paper_id=42)])
        self.assertEqual(step["paper_id"], 42)
        self.assertTrue(step["thumbnail_url"].startswith("/api/v1/catalog/papers/42/preview/"))


class LoadTest(unittest.TestCase):
    def test_dry_run_only_reads(self):
        db = FakeSession([current()])
        steps = loader.load(db, [entry(b"new")], execute=False)
        self.assertEqual(steps[0]["action"], "insert")
        self.assertEqual(db.writes(), [])
        self.assertFalse(any("advisory" in s for s in db.statements))

    def test_execute_writes_preview_and_thumbnail_url(self):
        db = FakeSession([current()])
        loader.load(db, [entry(b"new")], execute=True)
        writes = db.writes()
        self.assertEqual(len(writes), 2)
        self.assertTrue(writes[0].startswith("INSERT INTO discovery_previews"))
        self.assertTrue(writes[1].startswith("UPDATE papers SET thumbnail_url"))

    def test_execute_skips_without_writing(self):
        db = FakeSession([current(thumbnail_url="https://cdn.example.com/x.jpg")])
        loader.load(db, [entry(b"new")], execute=True)
        self.assertEqual(db.writes(), [])

    def test_refuses_other_databases(self):
        with self.assertRaises(RuntimeError):
            loader.load(FakeSession([], database=("pwc", "pwc")), [], execute=False)


if __name__ == "__main__":
    unittest.main()
