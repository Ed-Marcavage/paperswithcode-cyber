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

    def test_rejects_pins_outside_posts_or_repeated(self):
        post = {"url": "https://a.example/1", "company": "A", "title": "One"}
        for pinned in (["https://other.example/"], [post["url"], post["url"]], "https://a.example/1"):
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
        self.assertEqual(sorted(e["curated_pin"] for e in entries.values() if "curated_pin" in e), [1, 2, 3, 4, 5, 6])


if __name__ == "__main__":
    unittest.main()
