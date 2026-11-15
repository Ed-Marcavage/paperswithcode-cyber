"""Bounded assistant-only post search using the existing assistant session pool."""

import json
import logging
import time

import anyio
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from backend.models.assistant_tools import FindPostsArguments
from backend.services import trending_posts
from backend.services.assistant_catalog_links import paper_path
from backend.services.assistant_tool_budget import SUMMARY_CHARS
from backend.services.publishers import PUBLISHER_ORGANIZATION_SQL, host_table

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

# Only fixed SQL fragments are composed here. Every filter, mapping and date is
# a bind parameter. Resolve publisher before filtering/limiting, matching the
# curated -> linked -> longest mapped host -> raw host priority in publishers.py.
logger = logging.getLogger(__name__)

BASE_SQL = r"""
WITH posts AS (
    SELECT p.id, p.title, p.date_published, w.facets, w.post_details, w.source_url,
           substring(w.source_url from '(?i)^https?://(?\:www[.])?([^/:?#]+)') AS source_host,
           """ + PUBLISHER_ORGANIZATION_SQL.format(paper_id="p.id") + r""" AS organization
      FROM discovery_works w JOIN papers p ON p.id = w.paper_id
     WHERE w.facets -> 'kind' ? 'post' AND w.post_details IS NOT NULL
), anchor AS (
    SELECT coalesce(CAST(:anchor AS date), max(date_published)::date) AS day FROM posts
), scored AS (
    SELECT posts.*,
           coalesce(nullif(btrim(post_details ->> 'curated_company'), ''), nullif(btrim(organization), ''),
               (SELECT value FROM jsonb_each_text(CAST(:publisher_hosts AS jsonb))
                 WHERE lower(source_host) = key OR lower(source_host) LIKE '%.' || key
                 ORDER BY length(key) DESC LIMIT 1), lower(source_host)) AS publisher,
           coalesce((post_details ->> 'technical_depth')::integer, 0)
           + coalesce((post_details ->> 'originality')::integer, 0)
           + CASE WHEN post_details ->> 'agent_harness_engineering' = 'true' THEN 1 ELSE 0 END AS score
      FROM posts
), matched AS (
    SELECT scored.*, CASE WHEN date_published IS NULL THEN 0 ELSE
           score * power(0.5, greatest(anchor.day - date_published::date, 0)::double precision / :half_life)
           END AS score_recent
      FROM scored CROSS JOIN anchor
     WHERE true
"""
ORDERS = {"score": "score DESC", "recent": "date_published DESC NULLS LAST", "score_recent": "score_recent DESC"}


TEXT_VECTOR = "to_tsvector('english', coalesce(title, '') || ' ' || coalesce(post_details ->> 'tldr', ''))"
ALL_WORDS = "plainto_tsquery('english', :query)"
# Assemble OR from PostgreSQL-normalized, individually quoted lexemes. The raw
# query is always a bound value, never SQL or tsquery syntax supplied by a model.
ANY_WORD = """CAST((SELECT string_agg(quote_literal(term), ' | ')
    FROM unnest(tsvector_to_array(to_tsvector('english', :query))) AS words(term)) AS tsquery)"""


def search_statement(arguments, *, any_word=False, relax_relevance=False):
    args = FindPostsArguments.model_validate(arguments)
    params = {"min_agent_relevance": args.min_agent_relevance, "limit": args.limit,
              "anchor": trending_posts.ANCHOR_DATE, "half_life": trending_posts.DECAY_HALF_LIFE_DAYS,
              "publisher_hosts": json.dumps(host_table())}
    clauses = []
    if not relax_relevance:
        clauses.append("AND coalesce((post_details ->> 'agent_relevance')::integer, -1) >= :min_agent_relevance")
    if args.query:
        # The model supplies keywords, not necessarily a verbatim phrase. Use
        # PostgreSQL's built-in English stemming, as the catalog paper search does.
        params["query"] = args.query
        clauses.append(f"AND {TEXT_VECTOR} @@ {ANY_WORD if any_word else ALL_WORDS}")
    if args.topic:
        params["topic"] = json.dumps({"topic": [args.topic]})
        clauses.append("AND facets @> CAST(:topic AS jsonb)")
    if args.subtopic:
        params["subtopic"] = args.subtopic
        clauses.append("AND EXISTS (SELECT 1 FROM jsonb_array_elements_text(coalesce(post_details -> 'subtopics', '[]'::jsonb)) AS st(value) WHERE lower(st.value) = lower(:subtopic))")
    for field in ("post_type", "tier"):
        if value := getattr(args, field):
            params[field] = value
            clauses.append(f"AND post_details ->> '{field}' = :{field}")
    if args.publisher:
        params["publisher"] = args.publisher
        clauses.append("AND lower(publisher) = lower(:publisher)")
    if args.harness_engineering is not None:
        params["harness_engineering"] = args.harness_engineering
        clauses.append("AND (post_details ->> 'agent_harness_engineering')::boolean = :harness_engineering")
    if args.published_after:
        params["published_after"] = args.published_after
        clauses.append("AND date_published::date > :published_after")
    order = f"ts_rank_cd({TEXT_VECTOR}, {ANY_WORD}) DESC, score DESC" if any_word else ORDERS[args.sort]
    sql = BASE_SQL + "\n".join(clauses) + """
) SELECT id, title, date_published, source_url, post_details, publisher,
         count(*) OVER () AS total FROM matched ORDER BY """ + order + ", date_published DESC NULLS LAST, id DESC LIMIT :limit"
    return text(sql), params


def short(value):
    return value[:SUMMARY_CHARS] + "…" if isinstance(value, str) and len(value) > SUMMARY_CHARS else value


def post_item(row):
    post = row["post_details"]
    published = row["date_published"]
    if hasattr(published, "date"):
        published = published.date()
    return {"id": row["id"], "title": row["title"], "publisher": row["publisher"],
            "published": published.isoformat() if published else None,
            **{key: post.get(key) for key in ("post_type", "tier", "agent_relevance", "technical_depth", "originality")},
            "harness_engineering": post.get("agent_harness_engineering"),
            "tldr": short(post.get("tldr")), "caveat": short(post.get("caveat")),
            "subtopics": post.get("subtopics") or [], "source_url": row["source_url"],
            "catalog_url": paper_path(row["id"])}


def read_posts(arguments, sessions=None, deadline=None):
    args = FindPostsArguments.model_validate(arguments)
    deadline = time.monotonic() + QUERY_SECONDS if deadline is None else deadline
    if sessions is None:
        from backend.database.assistant import assistant_sessions
        sessions = assistant_sessions()
    relaxations = []
    relaxed_relevance = False
    any_word = False
    # All attempts share one read-only transaction and one wall-clock budget.
    with sessions() as db:
        db.execute(text("SET TRANSACTION READ ONLY"))

        def search():
            remaining_ms = int((deadline - time.monotonic()) * 1000)
            if remaining_ms <= 0:
                raise TimeoutError()
            db.execute(text("SELECT set_config('statement_timeout', :timeout, true)"),
                       {"timeout": str(min(1500, remaining_ms))})
            statement, params = search_statement(arguments, any_word=any_word, relax_relevance=relaxed_relevance)
            return list(db.execute(statement, params).mappings())

        def sparse(rows):
            # A requested limit of one must not loosen a query with many matches.
            return not rows or int(rows[0]["total"]) < 3

        rows = search()
        if args.query and sparse(rows) and "min_agent_relevance" not in arguments:
            relaxed_relevance = True
            relaxations.append("Removed the default agent relevance filter to include broader reporting.")
            rows = search()
        if args.query and sparse(rows):
            any_word = True
            relaxations.append("Loosened text matching from all words to any word; ranked by text relevance, then score.")
            rows = search()
    result = {"total": int(rows[0]["total"]) if rows else 0, "results": [post_item(row) for row in rows],
              "sort": "text_rank_then_score" if any_word else args.sort,
              "match_mode": "any_word" if any_word else "all_words" if args.query else "filters",
              "relaxations": relaxations}
    if not rows:
        # Keep the advice specific to the strongest optional restriction.
        field = next((key for key in ("query", "subtopic", "publisher", "post_type", "published_after", "topic", "tier") if arguments.get(key)), None)
        hint = f"Loosen or remove {field} first." if field else "Try min_agent_relevance=0 or omit harness_engineering."
        result.update(message="Zero posts match these filters; this does not establish missing catalog coverage.", hint=hint)
    return result


async def find_posts(arguments, sessions=None):
    try:
        with anyio.fail_after(QUERY_SECONDS):
            return await anyio.to_thread.run_sync(read_posts, arguments, sessions, time.monotonic() + QUERY_SECONDS,
                                                abandon_on_cancel=True), False
    except (SQLAlchemyError, OSError, TimeoutError) as error:
        # Never include DB connection details, SQL or bound arguments in errors.
        # Log the failure by type only, so a broken query is visible to the operator.
        logger.warning("assistant find_posts failed: %s", type(error).__name__)
        return {"error": "Post search is temporarily unavailable. Try browse_catalog or search_papers; this is not a zero-match result."}, True
