import asyncio
import json
import time
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy.exc import SQLAlchemyError

from backend.services import assistant_post_metadata as metadata
from backend.services.assistant_loop import PROMPT_VERSION, SYSTEM_PROMPT
from backend.services.assistant_mcp import CatalogMcp
from backend.tests.assistant.test_mcp import response


ROWS = {
    1: {"paper_id": 1, "source_url": "https://blog.cloudflare.com/post", "publisher_organization": "Linked publisher",
        "post_details": {"curated_company": "Curated publisher", "post_type": "engineering", "tier": "featured", "agent_relevance": 4, "tldr": "Builds isolated agent harnesses."}},
    2: {"paper_id": 2, "source_url": "https://blog.cloudflare.com/post", "publisher_organization": "Linked publisher",
        "post_details": {"post_type": "research", "tier": "catalog", "agent_relevance": 0, "tldr": "General threat research."}},
}


def adapted(tool, payload, lookup, *, structured=True, error=False):
    envelope = {"structuredContent": payload} if structured else {"content": [{"type": "text", "text": json.dumps(payload)}]}
    envelope["isError"] = error
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: response(r, envelope))) as http:
            return await CatalogMcp(http, "http://catalog.test/mcp", lookup=lookup).call(tool, {})
    return asyncio.run(go())


@pytest.mark.parametrize("tool,structured", [("search_papers", True), ("browse_catalog", True), ("search_papers", False)])
def test_work_items_get_one_batch_lookup_and_curated_fields_before_byte_cap(tool, structured):
    calls = []
    def lookup(ids):
        calls.append(ids)
        return ROWS
    works = [{"id": "1", "title": "Agent harness", "abstract": "Old summary"},
             {"paper_id": "2", "title": "Threats"}, {"id": "3", "title": "Paper without post metadata"}]
    raw = {"schema_version": "v1", "data": {"results": works}, "items": works} if tool == "search_papers" else {"results": works}
    result = adapted(tool, raw, lookup, structured=structured)
    assert calls == [[1, 2, 3]]
    items = json.loads(result.text)["results"]
    assert items[0]["publisher"] == "Curated publisher"
    assert items[0]["catalog_url"] == "/paper/1"
    assert items[0]["post_type"] == "engineering" and items[0]["tier"] == "featured"
    assert items[0]["agent_relevance"] == 4 and items[0]["tldr"] == "Builds isolated agent harnesses."
    assert "abstract" not in items[0]
    assert items[1]["publisher"] == "Linked publisher" and items[1]["agent_relevance"] == 0
    assert "publisher" not in items[2] and "agent_relevance" not in items[2]
    assert result.full_bytes == len(result.text.encode())


def test_duplicate_nested_work_ids_are_looked_up_once_and_missing_ids_are_not_guessed():
    calls = []
    def lookup(ids):
        calls.append(ids)
        return ROWS
    result = adapted("get_paper_info", {"in_catalog": True,
        "paper": {"id": "1", "title": "Harness"}, "discovery": {"paper_id": "1", "title": "Harness"}}, lookup)
    payload = json.loads(result.text)
    assert calls == [[1]]
    assert payload["paper"]["publisher"] == payload["discovery"]["publisher"] == "Curated publisher"
    adapted("browse_catalog", {"results": [{"title": "No ID", "source_url": "https://example.test"}]}, lookup)
    adapted("catalog_filters", {"id": "1", "title": "Not a work", "topic": {"security": "Security"}}, lookup)
    adapted("get_paper_info", {"in_catalog": False, "paper": {"id": "1", "title": "Missing"}}, lookup)
    adapted("search_papers", {"results": [{"id": "1", "title": "Error"}]}, lookup, error=True)
    assert calls == [[1]]


def test_lookup_count_and_summary_length_are_bounded():
    calls = []
    def lookup(ids):
        calls.append(ids)
        return {i: {**ROWS[1], "post_details": {**ROWS[1]["post_details"], "tldr": "x" * 10000}} for i in ids}
    result = adapted("browse_catalog", {"results": [{"id": str(i), "title": "Post"} for i in range(1, 50)]}, lookup)
    assert calls == [list(range(1, 11))]
    assert all(len(w["tldr"]) == 601 for w in json.loads(result.text)["results"])
    assert len(result.text.encode()) <= 16384


def test_failed_or_timed_out_lookup_preserves_tool_result_and_logs_no_exception(monkeypatch, caplog):
    def fail(ids):
        raise SQLAlchemyError("private connection details")
    raw = {"results": [{"paper_id": "1", "title": "Still useful"}]}
    result = adapted("browse_catalog", raw, fail)
    assert json.loads(result.text)["post_metadata_status"] == "unavailable"
    assert "Still useful" in result.text and not result.is_error
    assert "private connection" not in result.text + caplog.text
    monkeypatch.setattr(metadata, "LOOKUP_SECONDS", .01)
    def slow(ids):
        time.sleep(.1)
        return ROWS
    result = adapted("browse_catalog", raw, slow)
    assert json.loads(result.text)["post_metadata_status"] == "unavailable"


def test_publisher_resolution_uses_existing_link_host_fallback_and_unknown_relevance():
    assert metadata.fields_for_post({**ROWS[2], "publisher_organization": None})["publisher"] == "Cloudflare"
    unknown = metadata.fields_for_post({"source_url": "https://unknown.test/post", "post_details": None})
    assert unknown["publisher"] == "unknown.test" and unknown["agent_relevance"] is None
    assert metadata.fields_for_post({**ROWS[1], "post_details": {"agent_relevance": 9}})["agent_relevance"] is None


def test_database_lookup_is_one_parameterized_select_with_readonly_connection_limits(monkeypatch):
    executions, options = [], []
    class Connection:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def execute(self, sql, params):
            executions.append((str(sql), params))
            return SimpleNamespace(mappings=lambda: list(ROWS.values()))
    def engine(url, **kwargs):
        options.append(kwargs)
        return SimpleNamespace(connect=Connection)
    monkeypatch.setattr(metadata, "get_settings", lambda: SimpleNamespace(database_url="postgresql://fake/test", db_search_path="public"))
    monkeypatch.setattr(metadata, "create_engine", engine)
    metadata.lookup_engine.cache_clear()
    try:
        assert metadata.lookup_post_metadata(list(range(1, 30))) == ROWS
    finally:
        metadata.lookup_engine.cache_clear()
    assert len(executions) == 1
    sql, params = executions[0]
    assert sql.lstrip().startswith("SELECT") and "paper_organizations" in sql
    assert params == {"paper_ids": list(range(1, 11)), "row_limit": 10}
    assert options[0]["connect_args"]["connect_timeout"] == 1
    assert "default_transaction_read_only=on" in options[0]["connect_args"]["options"]
    assert "statement_timeout=1000" in options[0]["connect_args"]["options"]
    assert options[0]["echo"] is False and options[0]["pool_timeout"] == 1


def test_prompt_focuses_agent_harness_posts_without_overclaiming_rankings():
    assert PROMPT_VERSION == "cyber-assistant-v8"
    for phrase in ("AI agent harnesses", "agent_relevance of 3", "vulnerabilities, malware or threats",
                   "tldr", "Group by publisher", "limited search samples"):
        assert phrase in SYSTEM_PROMPT
