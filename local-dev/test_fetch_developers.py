import unittest
from unittest.mock import patch

from fetch_developers import collect


class CollectDeveloperTests(unittest.TestCase):
    repo = {"id": 101, "full_name": "alice/tool", "private": False,
            "owner": {"id": 1, "login": "alice", "type": "User"}}

    def test_owner_is_one_account_and_all_pages_are_used(self):
        pages = [[{"id": 1, "login": "alice", "type": "User", "contributions": 3}],
                 [{"id": 2, "login": "bob", "type": "User", "contributions": 1},
                  {"id": 3, "login": "robot", "type": "Bot", "contributions": 1}]]
        with patch("fetch_developers.github", side_effect=[self.repo, pages]) as api:
            snapshot = collect("old-name/tool")
        self.assertEqual(snapshot["catalog_name"], "old-name/tool")
        self.assertEqual(snapshot["full_name"], "alice/tool")
        api.assert_called_with("repos/alice/tool/contributors?per_page=100", "--paginate", "--slurp")
        self.assertEqual(snapshot["users"], [
            dict(id=1, login="alice", owns=True, commits=3),
            dict(id=2, login="bob", owns=False, commits=1),
        ])

    def test_ownership_alone_does_not_earn_commits(self):
        with patch("fetch_developers.github", side_effect=[self.repo, [None]]):
            self.assertEqual(collect("alice/tool")["users"], [dict(id=1, login="alice", owns=True, commits=0)])

    def test_an_organization_is_not_a_developer(self):
        org = dict(self.repo, owner=dict(id=9, login="team", type="Organization"))
        with patch("fetch_developers.github", side_effect=[org, []]):
            self.assertEqual(collect("team/tool")["users"], [])

    def test_private_repo_is_never_collected(self):
        with patch("fetch_developers.github", return_value=dict(self.repo, private=True)) as api:
            with self.assertRaisesRegex(ValueError, "private"):
                collect("alice/tool")
            api.assert_called_once()
