"""Curated-post manifest validation and URL matching; no database."""
import json
import unittest

from mark_curated_posts import MANIFEST, load_manifest, match, normalize_url


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

    def test_rejects_bad_entries(self):
        for data in [{}, [{"url": "https://a.b", "company": "", "title": "T"}],
                     [{"url": "a.b/x", "company": "C", "title": "T"}],
                     [{"url": "https://a.b/x", "company": "C", "title": "T"},
                      {"url": "http://www.a.b/x/", "company": "C", "title": "T"}]]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                load_manifest(data)

    def test_checked_in_manifest_is_valid(self):
        self.assertGreater(len(load_manifest(json.loads(MANIFEST.read_text()))), 0)


if __name__ == "__main__":
    unittest.main()
