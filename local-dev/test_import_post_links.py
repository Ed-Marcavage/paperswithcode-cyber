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
