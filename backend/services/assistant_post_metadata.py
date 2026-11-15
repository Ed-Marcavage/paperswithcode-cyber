"""One bounded read-only post-metadata lookup per MCP result, never per item."""

from functools import lru_cache

import anyio
from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from backend.config import get_settings
from backend.services.assistant_tool_budget import MAX_ITEMS, SUMMARY_CHARS
from backend.services.publishers import PUBLISHER_ORGANIZATION_SQL, publisher_name

LOOKUP_SECONDS = 2
MAX_POST_IDS = MAX_ITEMS
POST_METADATA_SQL = text("""
    SELECT w.paper_id, w.source_url, w.post_details,
           """ + PUBLISHER_ORGANIZATION_SQL.format(paper_id="w.paper_id") + """ AS publisher_organization
      FROM discovery_works w
     WHERE w.paper_id IN :paper_ids AND w.facets -> 'kind' ? 'post'
     LIMIT :row_limit
""").bindparams(bindparam("paper_ids", expanding=True))


@lru_cache(maxsize=1)
def lookup_engine():
    settings = get_settings()
    # A small separate read-only pool also bounds checkout, connection and SQL
    # time. Do not log SQL/parameters or DB exceptions (which can carry secrets).
    return create_engine(settings.database_url, connect_args={
        "connect_timeout": 1,
        "options": "-c default_transaction_read_only=on -c statement_timeout=1000 "
                   f"-c search_path={settings.db_search_path}",
    }, pool_size=1, max_overflow=1, pool_timeout=1, echo=False)


def lookup_post_metadata(paper_ids):
    with lookup_engine().connect() as connection:
        rows = connection.execute(POST_METADATA_SQL, {"paper_ids": paper_ids[:MAX_POST_IDS], "row_limit": MAX_POST_IDS}).mappings()
        return {int(row["paper_id"]): dict(row) for row in rows}


def work_items(payload):
    if isinstance(payload, list):
        for item in payload[:MAX_ITEMS]:
            yield from work_items(item)
    elif isinstance(payload, dict) and payload.get("in_catalog") is not False:
        if str(payload.get("catalog_url", "")).startswith("/paper/"):
            for field in ("paper_id", "id", "paper"):
                value = payload.get(field)
                if not isinstance(value, bool) and isinstance(value, (str, int)) and str(value).isdigit():
                    paper_id = int(value)
                    if 0 < paper_id <= 9223372036854775807:
                        yield paper_id, payload
                        break
        for key in ("results", "items", "data", "paper", "discovery", "top_trending_paper"):
            if key in payload:
                yield from work_items(payload[key])


def fields_for_post(row):
    post = row.get("post_details")
    if not isinstance(post, dict):
        post = {}
    summary = post.get("tldr")
    if isinstance(summary, str) and len(summary) > SUMMARY_CHARS:
        summary = summary[:SUMMARY_CHARS] + "…"
    relevance = post.get("agent_relevance")
    return {"publisher": publisher_name(row.get("source_url"), post.get("curated_company"), row.get("publisher_organization")),
            "post_type": post.get("post_type"), "tier": post.get("tier"),
            "agent_relevance": relevance if type(relevance) is int and 0 <= relevance <= 4 else None,
            "tldr": summary}


async def enrich_posts(payload, lookup=lookup_post_metadata):
    items = list(work_items(payload))
    ids = list(dict.fromkeys(paper_id for paper_id, _ in items))[:MAX_POST_IDS]
    if not ids:
        return payload
    try:
        with anyio.fail_after(LOOKUP_SECONDS):
            rows = await anyio.to_thread.run_sync(lookup, ids, abandon_on_cancel=True)
        metadata = {paper_id: fields_for_post(row) for paper_id, row in rows.items() if paper_id in ids}
    except (SQLAlchemyError, OSError, TimeoutError, ValueError):
        # A missing local table, unavailable DB or bad stored URL must not break
        # otherwise useful MCP evidence. Do not guess a missing relevance score.
        if isinstance(payload, dict):
            payload["post_metadata_status"] = "unavailable"
        return payload
    for paper_id, item in items:
        if fields := metadata.get(paper_id):
            item.update(fields)
            if fields.get("tldr"):
                item.pop("abstract", None)  # Prefer the curated post summary.
    return payload
