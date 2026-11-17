"""Curated-post manifest validation and URL matching; no database."""
import json
import unittest
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from mark_curated_posts import CURATED_KEYS, MANIFEST, load_manifest, main, match, normalize_url


class FakeSession:
    """Model curator updates in memory, checking the NULL and no-op SQL guards."""

    def __init__(self, rows):
        self.rows = deepcopy(rows)
        self.saved = deepcopy(rows)
        self.migrated = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        if "current_database()" in sql:
            return SimpleNamespace(one=lambda: ("pwc_local", "pwc_local"))
        if "ADD COLUMN IF NOT EXISTS curated_pin integer" in sql:
            self.migrated = True
        if sql.startswith("SELECT catalog_id"):
            assert self.migrated
            reviewed = "post_details IS NOT NULL" in sql
            return SimpleNamespace(all=lambda: [(key, row["url"]) for key, row in self.rows.items()
                                                if not reviewed or (row["kind"] == "post" and row["post"] is not None)])
        changed = 0
        if sql.startswith("UPDATE"):
            before = deepcopy(self.rows)
            for key, row in self.rows.items():
                if "SET curated_pin = :pin" in sql:
                    assert "curated_pin IS DISTINCT FROM :pin" in sql
                    if key == params["id"]:
                        row["pin"] = params["pin"]
                elif "SET curated_pin = NULL" in sql:
                    if key not in params["ids"]:
                        row["pin"] = None
                elif "SET post_details = (" in sql:
                    assert "post_details IS NOT NULL" in sql and "post_details IS DISTINCT FROM" in sql
                    if key == params["id"] and row["post"] is not None:
                        row["post"] = {k: v for k, v in row["post"].items() if k not in CURATED_KEYS}
                        row["post"].update(json.loads(params["fields"]))
                elif "SET post_details = post_details -" in sql:
                    if key not in params["ids"] and row["post"] is not None:
                        row["post"] = {k: v for k, v in row["post"].items() if k not in CURATED_KEYS}
                else:
                    raise AssertionError(sql)
            changed = sum(row != before[key] for key, row in self.rows.items())
        return SimpleNamespace(rowcount=changed)

    def commit(self):
        self.saved = deepcopy(self.rows)

    def rollback(self):
        self.rows = deepcopy(self.saved)


class CuratedPostsTest(unittest.TestCase):
    def test_normalize_url_ignores_scheme_www_fragment_and_trailing_slash(self):
        self.assertEqual(normalize_url("https://www.Wiz.io/blog/x/#top"), "wiz.io/blog/x")
        self.assertEqual(normalize_url("http://wiz.io/blog/x"), "wiz.io/blog/x")

    def test_matches_posts_and_reports_the_rest(self):
        entries = load_manifest([
            {"url": "https://www.wiz.io/blog/x/", "company": "Wiz", "title": " Arena "},
            {"url": "https://example.com/missing", "company": "Example", "title": "Missing"},
        ])
        matched, unmatched = match(entries, [("industry-1", "http://wiz.io/blog/x"), ("industry-2", "https://o.ther/")])
        self.assertEqual(matched, {"industry-1": {"curated": True, "curated_company": "Wiz", "curated_title": "Arena"}})
        self.assertEqual(unmatched, ["example.com/missing"])

    def test_pinned_urls_get_their_position(self):
        entries = load_manifest({
            "pinned": ["https://b.example/2", "http://www.a.example/1/"],
            "posts": [{"url": "https://a.example/1", "company": "A", "title": "One"},
                      {"url": "https://b.example/2", "company": "B", "title": "Two"},
                      {"url": "https://c.example/3", "company": "C", "title": "Three"}],
        })
        self.assertEqual(entries["b.example/2"]["curated_pin"], 1)
        self.assertEqual(entries["a.example/1"]["curated_pin"], 2)
        self.assertNotIn("curated_pin", entries["c.example/3"])

    def test_accepts_pinned_urls_outside_posts(self):
        entries = load_manifest({"pinned": ["https://arxiv.org/abs/2609.18120", "https://example.com/post"],
                                 "posts": []})
        self.assertEqual(entries, {"arxiv.org/abs/2609.18120": {"curated_pin": 1},
                                   "example.com/post": {"curated_pin": 2}})

    def test_arxiv_versions_match_every_catalog_work(self):
        entries = load_manifest({"pinned": ["https://arxiv.org/abs/2609.18120v3"], "posts": []})
        matched, unmatched = match(entries, [("paper-1", "https://arxiv.org/abs/2609.18120v2"),
                                              ("paper-2", "https://arxiv.org/abs/2609.18120")])
        self.assertEqual(matched, {"paper-1": {"curated_pin": 1}, "paper-2": {"curated_pin": 1}})
        self.assertEqual(unmatched, [])
        self.assertEqual(normalize_url("https://example.com/abs/2609.18120v2"), "example.com/abs/2609.18120v2")

    def test_rejects_repeated_or_invalid_pins(self):
        post = {"url": "https://a.example/1", "company": "A", "title": "One"}
        for pinned in ([post["url"], post["url"]], "https://a.example/1", ["not-a-url"],
                       [post["url"], "http://www.a.example/1/#top"],
                       ["https://arxiv.org/abs/2609.18120", "https://arxiv.org/abs/2609.18120v2"]):
            with self.subTest(pinned=pinned), self.assertRaises(ValueError):
                load_manifest({"pinned": pinned, "posts": [post]})

    def test_rejects_bad_entries(self):
        for data in [{}, [{"url": "https://a.b", "company": "", "title": "T"}],
                     [{"url": "a.b/x", "company": "C", "title": "T"}],
                     [{"url": "https://a.b/x", "company": "C", "title": "T"},
                      {"url": "http://www.a.b/x/", "company": "C", "title": "T"}]]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                load_manifest(data)

    def test_checked_in_manifest_is_valid(self):
        entries = load_manifest(json.loads(MANIFEST.read_text()))
        self.assertGreater(len(entries), 0)
        self.assertEqual(sorted(e["curated_pin"] for e in entries.values() if "curated_pin" in e), list(range(1, 10)))
        self.assertEqual(entries["arxiv.org/abs/2609.18120"], {"curated_pin": 1})
        self.assertEqual(entries["boozallen.com/insights/cyber/cyber-weapon-index.html"], {"curated_pin": 2})
        trail = entries["blog.trailofbits.com/2026/10/21/your-ai-agent-fixed-the-bug-but-what-else-did-it-change"]
        self.assertEqual(trail["curated_pin"], 3)
        self.assertEqual(trail["curated_company"], "Trail of Bits")

    def test_apply_mirrors_only_reviews_clears_stale_pins_and_is_idempotent(self):
        from backend.database.connection import db_manager

        rows = {
            "paper": {"url": "https://arxiv.org/abs/2609.18120v2", "kind": "paper", "post": None, "pin": None},
            "unreviewed": {"url": "https://example.com/unreviewed", "kind": "post", "post": None, "pin": None},
            "reviewed": {"url": "https://example.com/reviewed", "kind": "post", "post": {"tldr": "Review"}, "pin": None},
            "curated": {"url": "https://example.com/curated", "kind": "post", "post": {"tldr": "Review"}, "pin": 1},
            "stale": {"url": "https://example.com/stale", "kind": "post",
                      "post": {"tldr": "Keep", "curated": True, "curated_pin": 2}, "pin": 2},
        }
        manifest = {"pinned": ["https://arxiv.org/abs/2609.18120", rows["unreviewed"]["url"],
                               rows["reviewed"]["url"], rows["curated"]["url"], "https://example.com/missing-pin"],
                    "posts": [{"url": rows["curated"]["url"], "company": "Example", "title": "Curated"},
                              {"url": "https://example.com/missing-post", "company": "Missing", "title": "Missing"}]}
        db = FakeSession(rows)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps(manifest))

            def run(execute):
                output = StringIO()
                with patch.object(db_manager, "_engine", SimpleNamespace(echo=False)), \
                     patch.object(db_manager, "_session_local", lambda: db), \
                     patch("sys.argv", ["mark_curated_posts.py", str(path)] + (["--execute"] if execute else [])), \
                     redirect_stdout(output):
                    main()
                return json.loads(output.getvalue())

            preview = run(False)
            self.assertEqual(db.rows, rows)
            self.assertEqual((preview["pins_updated"], preview["pins_cleared"]), (4, 1))
            result = run(True)
            self.assertEqual(result["unmatched_urls"], ["https://example.com/missing-post"])
            self.assertEqual(result["unmatched_pinned_urls"], ["https://example.com/missing-pin"])
            self.assertEqual([db.rows[key]["pin"] for key in rows], [1, 2, 3, 4, None])
            self.assertIsNone(db.rows["paper"]["post"])
            self.assertIsNone(db.rows["unreviewed"]["post"])
            self.assertEqual(db.rows["reviewed"]["post"], {"tldr": "Review", "curated_pin": 3})
            self.assertEqual(db.rows["curated"]["post"], {"tldr": "Review", "curated": True,
                             "curated_company": "Example", "curated_title": "Curated", "curated_pin": 4})
            self.assertEqual(db.rows["stale"]["post"], {"tldr": "Keep"})
            rerun = run(True)
            self.assertEqual([rerun[key] for key in ("updated", "cleared", "pins_updated", "pins_cleared")], [0] * 4)


if __name__ == "__main__":
    unittest.main()
