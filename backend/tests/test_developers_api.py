"""Developers directory: agent-related work count and the default sort.

The routing and SQL-wiring tests run anywhere. The counting-rule tests run the service's real SQL
on PostgreSQL with the tables it reads shadowed by fixture CTEs, so they only read; they need an
explicit disposable database (PWC_TEST_DATABASE=1), like the other PostgreSQL-backed tests.
"""
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.config import get_settings
from backend.database.connection import get_database_session
from backend.services import discovery_developers, trending_posts


def directory_client(monkeypatch, seen):
    monkeypatch.setattr(get_settings(), "discovery_catalog", True)
    from backend.main import create_app
    from backend.routers import developers

    def fake(db, q, limit, offset, **kwargs):
        seen.append(kwargs)
        return {"count": 0, "results": []}

    monkeypatch.setattr(developers, "list_developers", fake)
    app = create_app()
    app.dependency_overrides[get_database_session] = lambda: object()
    return TestClient(app)


def test_default_sort_is_agent_related_work_and_old_sort_values_still_work(monkeypatch):
    seen = []
    client = directory_client(monkeypatch, seen)
    assert client.get("/api/v1/developers/").status_code == 200
    assert seen[-1]["sort"] == "agent"
    for sort in ("agent", "repos", "stars"):
        assert client.get(f"/api/v1/developers/?sort={sort}&q=al&topic=t&limit=5&offset=10").status_code == 200
        assert seen[-1]["sort"] == sort
        assert seen[-1]["filters"] == {"topic": "t", "target": "", "contribution": ""}
    assert client.get("/api/v1/developers/?sort=papers").status_code == 422


class Recorder:
    def __init__(self):
        self.calls = []

    def scalar(self, statement, params):
        self.calls.append((str(statement), params))
        return 0

    def execute(self, statement, params):
        self.calls.append((str(statement), params))

        class Rows(list):
            def mappings(self):
                return self
        return Rows()


@pytest.mark.parametrize("sort,order", [
    ("agent", "ORDER BY agent_work_count DESC, sum(commits) FILTER (WHERE agent_repo) DESC NULLS LAST, "
              "repository_count DESC, owned_stars DESC NULLS LAST, lower(login), github_id"),
    ("repos", "ORDER BY repository_count DESC, lower(login), github_id"),
    ("stars", "ORDER BY owned_stars DESC NULLS LAST, repository_count DESC, lower(login), github_id"),
])
def test_sql_uses_the_trending_threshold_and_each_sorts_tie_break(sort, order):
    db = Recorder()
    discovery_developers.list_developers(db, "", 24, 0, repository="", sort=sort,
                                         filters={"topic": ""}, include_facet_counts=True)
    assert len(db.calls) == 3
    for sql, params in db.calls:
        assert params["min_agent_relevance"] == trending_posts.MIN_AGENT_RELEVANCE == 3
        assert "WHERE pr.is_official" in sql
        assert "(w.post_details->>'agent_relevance')::numeric, 0) >= :min_agent_relevance" in sql
    assert order in " ".join(db.calls[1][0].split())


# --- Counting rule on PostgreSQL -------------------------------------------------------------

# repository_id n has github_repo_id 100 + n. (paper_id, kind, agent_relevance, links, topics);
# links are (repository_id, role) and a link is credited (is_official) for role "original" only,
# as local-dev/import_post_links.py sets it; papers' links are official implementations.
WORKS = [
    (1, "paper", None, [(1, "original"), (2, "original")], ["agents"]),  # alice, once despite two repos
    (2, "post", 3, [(1, "original")], ["web"]),           # alice: at the threshold
    (3, "post", 2, [(1, "original"), (4, "original")], []),  # below the threshold
    (4, "post", 4, [(1, "target")], []),                   # targets alice's repo: not credited
    (5, "post", 4, [(2, "dependency")], []),
    (6, "post", 4, [(2, "supporting")], []),
    (7, "post", None, [(2, "original")], []),             # no review score counts as 0
    (8, "repository", None, [(2, "original")], []),       # repository-kind works are not counted
    (9, "post", 4, [(3, "original")], []),                 # bob
    (10, "post", 3, [(3, "original")], []),                # bob
    (11, "post", 1, [(5, "original")], []),
    (12, "post", 1, [(6, "original")], []),
    (13, "post", 0, [(7, "original")], []),
]
# (github_id, login, repository_id, owns, commits); stars belong to repositories.
ACCOUNTS = [
    (1, "alice", 1, False, 5), (1, "alice", 2, False, 10), (1, "alice", 4, False, 1000),
    (2, "bob", 3, False, 50),
    (3, "carol", 5, True, 3), (4, "dave", 6, False, 3),
    (5, "eve", 5, False, 1), (5, "eve", 6, False, 1),
    (6, "Zed", 7, False, 1), (7, "amy", 7, False, 1),
]
STARS = {5: 500}


def fixture_tables() -> str:
    def rows(values):
        return ", ".join("(" + ", ".join(values_row) + ")" for values_row in values)

    def lit(value):
        return "NULL" if value is None else "TRUE" if value is True else "FALSE" if value is False else (
            repr(value) if isinstance(value, int) else "'" + value.replace("'", "''") + "'")

    repos = sorted({repo for *_, repo, _, _ in ACCOUNTS})
    works = [(lit(pid), "CAST(" + lit('{"kind": ["%s"], "topic": [%s]}' % (
        kind, ", ".join(f'"{t}"' for t in topics))) + " AS jsonb)",
              "CAST(NULL AS jsonb)" if relevance is None and kind != "post" else
              "CAST(" + lit("{}" if relevance is None else '{"agent_relevance": %d}' % relevance) + " AS jsonb)")
             for pid, kind, relevance, _, topics in WORKS]
    links = [(lit(pid), lit(repo), lit(role == "original"), lit(role))
             for pid, _, _, repo_links, _ in WORKS for repo, role in repo_links]
    return f"""
        discovery_developer_work(github_id, login, github_repo_id, full_name, owns, commits) AS (
            VALUES {rows((lit(g), lit(login), lit(100 + repo), lit(f"org/repo{repo}"), lit(owns), lit(commits))
                         for g, login, repo, owns, commits in ACCOUNTS)}),
        discovery_github_repo_snapshots(repository_id, github_repo_id) AS (
            VALUES {rows((lit(repo), lit(100 + repo)) for repo in repos)}),
        repositories(id, num_stars, num_stars_updated_at) AS (
            VALUES {rows((lit(repo), lit(STARS.get(repo, 1)), "CAST('2026-11-01' AS timestamptz)")
                         for repo in repos)}),
        paper_repositories(paper_id, repository_id, is_official, role) AS (VALUES {rows(links)}),
        discovery_works(paper_id, facets, post_details) AS (VALUES {rows(works)}),
    """


class FixtureSession:
    """Runs the service's statements with its tables shadowed by the fixture CTEs above."""

    def __init__(self, run):
        self.run = run

    def _rows(self, statement, params):
        sql = str(statement)
        assert sql.lstrip().startswith("WITH work AS")
        return self.run(text(sql.replace("WITH ", "WITH " + fixture_tables(), 1)), params)

    def scalar(self, statement, params):
        return next(iter(self._rows(statement, params)[0].values()))

    def execute(self, statement, params):
        rows = self._rows(statement, params)

        class Rows(list):
            def mappings(self):
                return list(rows)

            def __iter__(self):
                return (tuple(row.values()) for row in list.__iter__(self))
        return Rows(rows)


@pytest.fixture
def pg():
    if os.environ.get("PWC_TEST_DATABASE") != "1":
        pytest.skip("Requires explicit disposable PostgreSQL database")
    from backend.database.connection import db_manager
    with db_manager.engine.connect() as connection:
        yield FixtureSession(lambda statement, params: [dict(row) for row in connection.execute(
            statement, params).mappings()])
        connection.rollback()


def listing(pg, sort="agent", **kwargs):
    filters = {"topic": "", "target": "", "contribution": "", **kwargs.pop("filters", {})}
    return discovery_developers.list_developers(
        pg, kwargs.pop("q", ""), kwargs.pop("limit", 24), kwargs.pop("offset", 0), repository="",
        sort=sort, filters=filters, include_facet_counts=kwargs.pop("include_facet_counts", False))


def test_counts_distinct_papers_and_agent_related_posts_on_credited_repositories(pg):
    result = listing(pg)
    counts = {dev.login: dev.agent_work_count for dev in result.results}
    # alice: paper 1 (linked from two of her repos, counted once) and post 2 at the threshold.
    # Not counted: a post below the threshold, target/dependency/supporting links, a post
    # without a score, a repository-kind work.
    assert counts == {"alice": 2, "bob": 2, "carol": 0, "dave": 0, "eve": 0, "Zed": 0, "amy": 0}
    assert result.count == 7


def test_default_sort_breaks_ties_on_commits_to_credited_repos_then_repos_stars_and_login(pg):
    # bob ties alice on two works and wins on 50 commits to those repos against alice's 15; her 1000
    # commits to a repo only a below-threshold post credits do not count. Among developers without
    # agent-related work: more repos (eve), then owned stars (carol), then login, case-insensitive.
    assert [d.login for d in listing(pg).results] == ["bob", "alice", "eve", "carol", "amy", "dave", "Zed"]
    assert [d.login for d in listing(pg, limit=2, offset=1).results] == ["alice", "eve"]


def test_old_sorts_keep_their_order(pg):
    assert [d.login for d in listing(pg, "repos").results] == ["alice", "eve", "amy", "bob", "carol", "dave", "Zed"]
    assert [d.login for d in listing(pg, "stars").results] == ["carol", "alice", "eve", "amy", "bob", "dave", "Zed"]


def test_filters_and_search_narrow_the_count_to_matching_works(pg):
    result = listing(pg, filters={"topic": "agents"}, include_facet_counts=True)
    assert [(d.login, d.agent_work_count, d.repository_count) for d in result.results] == [("alice", 1, 2)]
    assert result.facet_counts["topic"]["agents"] == 1
    assert [(d.login, d.agent_work_count) for d in listing(pg, q="@BO").results] == [("bob", 2)]
