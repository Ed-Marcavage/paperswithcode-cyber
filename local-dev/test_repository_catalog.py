"""Local tests: no network, no persisted fixtures; DB integration rolls back."""
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import repository_catalog as catalog


def record(at=None, stars=100):
    return {'full_name': 'cyberintel-test/rollback-only',
            'url': 'https://github.com/cyberintel-test/rollback-only',
            'stars': stars, 'archived': False,
            'observed_at': (at or datetime.now(timezone.utc)).isoformat()}


class SnapshotValidation(unittest.TestCase):
    def test_bad_identity_or_count_rejected(self):
        for bad in [{'stars': -1}, {'stars': True}, {'url': 'https://example.com/project'},
                    {'full_name': '../invalid/path'}]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                catalog.validate_snapshot({**record(), **bad})

    def test_date_only_stale_and_future_rejected(self):
        now = datetime.now(timezone.utc)
        for at in [now.date().isoformat(), (now-timedelta(days=2)).isoformat(),
                   (now+timedelta(hours=1)).isoformat()]:
            with self.subTest(at=at), self.assertRaises(ValueError):
                catalog.validate_snapshot({**record(), 'observed_at': at}, now)

    def test_valid_precise_observation(self):
        now = datetime.now(timezone.utc)
        self.assertEqual(catalog.validate_snapshot(record(now), now), now)


class LocalDatabaseIntegration(unittest.TestCase):
    def test_upstream_cold_start_growth_and_negative_delta(self):
        from backend.models.database import Repository, RepositoryStarHistory
        with catalog.local_session() as db:
            try:
                repo = Repository(url=record()['url'], owner='cyberintel-test',
                                  name='rollback-only', source='cyberintel-local')
                db.add(repo)
                db.flush()
                now = datetime.now(timezone.utc)
                first = record(now-timedelta(hours=2))
                self.assertTrue(catalog.store_snapshot(db, repo, first))
                db.flush()
                # Upstream commits normally; suppress only that commit so synthetic
                # fixture rows never escape the surrounding rollback transaction.
                with patch.object(db, 'commit'):
                    self.assertEqual(catalog.score(db, [repo.id])['insufficient'], 1)
                    db.refresh(repo)
                    self.assertEqual(float(repo.trending_score), 0)
                    self.assertFalse(catalog.store_snapshot(db, repo, first))
                    self.assertEqual(db.query(RepositoryStarHistory).filter_by(repository_id=repo.id).count(), 1)
                    self.assertTrue(catalog.store_snapshot(db, repo, record(now-timedelta(hours=1), 110)))
                    db.flush()
                    self.assertEqual(catalog.score(db, [repo.id])['updated'], 1)
                    db.refresh(repo)
                    self.assertAlmostEqual(float(repo.trending_score), 7.5)
                    catalog.store_snapshot(db, repo, record(now, 100))
                    db.flush()
                    catalog.score(db, [repo.id])
                    db.refresh(repo)
                    self.assertEqual(float(repo.trending_score), 0)
            finally:
                db.rollback()
        with catalog.local_session() as db:
            self.assertEqual(db.query(Repository).filter_by(url=record()['url']).count(), 0)


class RefreshIntegration(unittest.TestCase):
    def setUp(self):
        from sqlalchemy import text
        self.db = self.enterContext(catalog.local_session())
        for table in ('repositories', 'repository_star_history'):
            self.db.execute(text(f'CREATE TEMP TABLE {table} AS SELECT * FROM public.{table} WITH NO DATA'))
        self.db.execute(text('ALTER TABLE repository_star_history ALTER COLUMN id SET NOT NULL, '
                             'ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY'))
        self.enterContext(patch.object(catalog, 'local_session', side_effect=lambda: nullcontext(self.db)))
        self.enterContext(patch.object(self.db, 'commit'))
        self.enterContext(patch.object(catalog, 'score'))
        self.at = datetime.now(timezone.utc) - timedelta(hours=3)
        self.clock = self.enterContext(patch.object(catalog, 'datetime', wraps=datetime))
        self.clock.now.return_value = self.at
        self.fetch = self.enterContext(patch.object(catalog, 'fetch_repository', side_effect=self.observation))

    def seed(self, id, observed, source='cyberintel-local'):
        from backend.models.database import Repository
        self.db.add(Repository(id=id, owner='test', name=str(id), url=f'https://github.com/test/{id}',
                               num_stars_updated_at=observed, source=source))

    def observation(self, name):
        return dict(full_name=name, url=f'https://github.com/{name}', stars=10, archived=False,
                    observed_at=self.clock.now.return_value.isoformat())

    def test_81_repositories_rotate_within_hourly_budget(self):
        for id in range(1, 82):
            self.seed(id, {81: None, 2: self.at-timedelta(hours=5), 1: self.at-timedelta(minutes=1)}.get(
                id, self.at-timedelta(hours=3)), 'cyberintel-local-archived' if id == 80 else 'cyberintel-local')
        self.seed(82, None, 'unmanaged')
        self.db.flush()
        cycles = []
        for hour in range(3):
            self.clock.now.return_value = self.at + timedelta(hours=hour)
            self.fetch.reset_mock()
            report = catalog.refresh()
            fetched = [int(call.args[0].split('/')[1]) for call in self.fetch.call_args_list]
            self.assertEqual(len(fetched), 30)
            self.assertEqual(report['refreshed'], 30)
            self.assertEqual(report['errors'], [])
            if hour == 0:
                self.assertEqual(fetched, [81, 2, *range(3, 31)])
                self.assertEqual(report['deferred'], 50)
                self.assertEqual(report['not_due'], 1)
            cycles.append(set(fetched))
        self.assertTrue(cycles[0].isdisjoint(cycles[1]))
        self.assertEqual(set.union(*cycles), set(range(1, 82)))

    def test_rate_limit_preserves_failed_and_unattempted_rows_for_retry(self):
        from backend.models.database import Repository, RepositoryStarHistory
        for id in range(1, 6):
            self.seed(id, None)
        self.db.flush()
        self.fetch.side_effect = [self.observation('test/1'), HTTPError('https://api.github.com', 429, 'rate limit', {}, None)]
        report = catalog.refresh()
        self.assertEqual(self.fetch.call_count, 2)
        self.assertEqual(report['refreshed'], 1)
        self.assertEqual(report['errors'][0]['repository'], 'test/2')
        self.assertEqual(report['deferred'], 3)
        self.assertIsNone(self.db.get(Repository, 2).num_stars_updated_at)
        self.assertEqual(self.db.query(RepositoryStarHistory).count(), 1)
        self.fetch.side_effect = self.observation
        self.fetch.reset_mock()
        report = catalog.refresh()
        self.assertEqual([call.args[0] for call in self.fetch.call_args_list], [f'test/{id}' for id in range(2, 6)])
        self.assertEqual(report['refreshed'], 4)
        self.assertEqual(self.db.query(RepositoryStarHistory).count(), 5)

    def test_overlapping_worker_skips_github_calls(self):
        from sqlalchemy import text
        from backend.database.connection import db_manager
        with db_manager.session_local() as other_worker:
            other_worker.execute(text("SELECT pg_advisory_xact_lock(hashtext('pwc_catalog_star_refresh'))"))
            self.assertEqual(catalog.refresh()['skipped'], 'refresh already running')
        self.fetch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
