"""Industry-post links: role selection without a database, and an idempotency
check against the local catalog that always rolls back."""
import json
from pathlib import Path
import unittest

import import_post_links as links


class DesiredLinksTest(unittest.TestCase):
    def test_one_link_per_repository_strongest_role_and_dropped_roles(self):
        chosen, skipped = links.desired_links([
            {"url": "https://github.com/Org/Tool/blob/main/a.py", "role": "supporting", "evidence": "Cited."},
            {"url": "https://github.com/org/tool.git", "role": "original", "evidence": " Released here. "},
            {"url": "https://github.com/org/other", "role": "unclear", "evidence": "?"},
            {"url": "https://github.com/org/menu", "role": "navigation", "evidence": "Site menu."},
            {"url": "https://gitlab.com/group/project", "role": "dependency", "evidence": "Uses it."},
            {"url": "https://github.com/advisories/GHSA-1234", "role": "target", "evidence": "Advisory."},
        ], "industry-test")
        self.assertEqual(list(chosen), ["org/tool"])
        self.assertEqual(chosen["org/tool"], ("org", "tool", "original", "Released here.", "https://github.com/org/tool.git"))
        self.assertEqual(skipped, {"role_unclear": 1, "role_navigation": 1, "not_a_github_repository": 2,
                                   "same_repository_again": 1})

    def test_unknown_role_is_an_error(self):
        with self.assertRaises(ValueError):
            links.desired_links([{"url": "https://github.com/a/b", "role": "owner"}], "industry-test")

    def test_only_original_is_credited_by_default(self):
        self.assertEqual(links.CREDITED_ROLES, {"original"})
        self.assertTrue(set(links.CREDITED_ROLES) <= set(links.IMPORTED_ROLES))

    def test_slug(self):
        self.assertEqual(links.slugify("Horizon3.ai"), "horizon3-ai")
        self.assertEqual(links.slugify("Palo Alto Networks"), "palo-alto-networks")


FIELDS = Path("/tmp/v2-fields.json")


@unittest.skipUnless(FIELDS.exists(), "copy bundle/v2-fields.json to /tmp/v2-fields.json in the backend")
class IdempotencyIntegration(unittest.TestCase):
    """Run the import twice in one transaction: the second run changes nothing. Rolls back."""

    def test_second_run_changes_nothing(self):
        from sqlalchemy import text
        reviews = json.loads(FIELDS.read_text())
        tables = ("organizations", "paper_organizations", "repositories", "paper_repositories")
        with links.local_session() as db:
            try:
                links.import_links(db, reviews)
                before = {t: db.scalar(text(f"SELECT count(*) FROM {t}")) for t in tables}
                again = links.import_links(db, reviews)
                after = {t: db.scalar(text(f"SELECT count(*) FROM {t}")) for t in tables}
                self.assertEqual({k: again[k] for k in links.CHANGE_COUNTS}, dict.fromkeys(links.CHANGE_COUNTS, 0))
                self.assertEqual(before, after)
            finally:
                db.rollback()


if __name__ == "__main__":
    unittest.main()


class PartialImportTest(unittest.TestCase):
    def test_missing_posts_and_fields_are_skipped_but_empty_lists_are_selected(self):
        posts = [(1, "absent", "https://example.com/a"), (2, "missing", "https://example.com/b"),
                 (3, "empty", "https://example.com/c")]
        reviews = {"missing": {}, "empty": {"code_links": []}}
        self.assertEqual(links.reviewed_posts(posts, reviews), [posts[2]])
        with self.assertRaisesRegex(ValueError, "Full replacement"):
            links.reviewed_posts(posts, reviews, replace_all=True)
        reviews = {p[1]: {"code_links": []} for p in posts}
        self.assertEqual(links.reviewed_posts(posts, reviews, replace_all=True), posts)
        with self.assertRaisesRegex(ValueError, "explicit list"):
            links.reviewed_posts(posts, {"empty": {"code_links": None}})

    def test_repository_changes_touch_only_explicit_posts_and_report_counts(self):
        from collections import Counter
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch
        posts = [(i, f"post-{i}", f"https://example.com/{i}") for i in range(1, 5)]
        existing = [SimpleNamespace(paper_id=i, repository_id=10, source=links.LINK_SOURCE)
                    for i in range(1, 4)]
        manifest = SimpleNamespace(paper_id=3, repository_id=11, source="manifest")
        db = MagicMock()
        db.query.return_value.filter.return_value = [*existing, manifest]
        repo = SimpleNamespace(id=12)
        reviews = {"post-2": {}, "post-3": {"code_links": []},
                   "post-4": {"code_links": [{"url": "https://github.com/example/project", "role": "original"}]}}
        counts = Counter()
        with patch.object(links, "known_repositories", return_value=({"example/project": repo}, set())):
            links.link_repositories(db, posts, reviews, counts)
        db.delete.assert_called_once_with(existing[2])
        self.assertEqual(db.add.call_args.args[0].paper_id, 4)
        self.assertEqual(counts["repository_links_removed"], 1)
        self.assertEqual(counts["repository_links_added"], 1)
        self.assertEqual(counts["changed_post_ids"], {3, 4})

    def test_import_filters_publishers_too_and_summarizes_dry_run_changes(self):
        from unittest.mock import MagicMock, patch
        posts = [(1, "absent", "https://example.com/a"), (2, "empty", "https://example.com/b")]
        db = MagicMock()
        db.execute.return_value.all.side_effect = [posts, []]
        def publishers(db, selected, counts):
            self.assertEqual(selected, [posts[1]])
            counts["publisher_links_added"] = 1
            links.changed_post(counts, 2)
        def repositories(db, selected, reviews, counts):
            self.assertEqual(selected, [posts[1]])
            counts["repository_links_removed"] = 2
            links.changed_post(counts, 2)
        with patch.object(links, "link_publishers", publishers), patch.object(links, "link_repositories", repositories):
            result = links.import_links(db, {"empty": {"code_links": []}})
        self.assertEqual((result["posts_changed"], result["links_added"], result["links_removed"], result["posts_skipped"]), (1, 1, 2, 1))
