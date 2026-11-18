"""Bounded assistant-only post search using the existing assistant session pool."""

import logging
import time

import anyio
from sqlalchemy.exc import SQLAlchemyError

from backend.services.catalog_posts import read_posts, search_statement

__all__ = ["DESCRIPTION", "find_posts", "read_posts", "search_statement"]

QUERY_SECONDS = 3
DESCRIPTION = """Prefer find_posts for ANY question about industry posts: engineering,
agent harnesses, benchmarking findings, defender reports and vulnerability triage/repair.
Matches keywords across titles and curated summaries, with English stemming; all terms
match first. With fewer than three matches, an implicit relevance filter is removed
first, then any-word matching ranks by text relevance before score if still sparse.
Results disclose these relaxations. Explicit relevance filters are always kept.
Prefer topic/type filters without a query when they express the question.
Combines reviewed post filters and ranks useful
posts instead of just newest titles. For best harness designs use harness_engineering=true
and sort=score, with one topic; avoid an over-specific query. Default relevance is 3;
use min_agent_relevance=0 for general vulnerability, malware or threat reporting.
Use browse_catalog and search_papers for research papers/repositories, and list_developers
for developers. score is technical_depth + originality + 1 for harness engineering;
score_recent uses Trending's seven-day half-life and newest-reviewed-post date anchor.
Returns at most 10 posts plus the full matching count. Shorten the query or loosen a
filter on zero matches; zero matches for a narrow request do not prove missing coverage."""

logger = logging.getLogger(__name__)


async def find_posts(arguments, sessions=None):
    if sessions is None:
        from backend.database.assistant import assistant_sessions
        sessions = assistant_sessions()
    try:
        with anyio.fail_after(QUERY_SECONDS):
            return await anyio.to_thread.run_sync(read_posts, arguments, sessions, time.monotonic() + QUERY_SECONDS,
                                                abandon_on_cancel=True), False
    except (SQLAlchemyError, OSError, TimeoutError) as error:
        # Never include DB connection details, SQL or bound arguments in errors.
        # Log the failure by type only, so a broken query is visible to the operator.
        logger.warning("assistant find_posts failed: %s", type(error).__name__)
        return {"error": "Post search is temporarily unavailable. Try browse_catalog or search_papers; this is not a zero-match result."}, True
