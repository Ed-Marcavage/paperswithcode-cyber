import asyncio
import copy
import json

import pytest

from backend.services.assistant_input_budget import (
    INPUT_TOKEN_BUDGET, FINAL_INPUT_TOKENS, estimate_input_tokens, finalizer_messages, history_token_estimate,
)
from backend.services.assistant_loop import SYSTEM_PROMPT, FINALIZER_PROMPT, TurnLimits
from backend.services.assistant_mcp import TOOL_NAMES, MAX_RESULT_BYTES
from backend.services.assistant_tool_budget import MAX_ITEMS, bounded_arguments
from backend.tests.assistant.test_loop import FakeServices, chunk, text_chunk, tool_chunk
from backend.tests.assistant.test_mcp import run, response


@pytest.mark.parametrize("name", ["search_papers", "browse_catalog", "list_developers", "list_recent_papers", "list_trending_papers", "get_related_papers"])
def test_list_size_is_clamped_before_network_and_defaults_to_ten(name):
    seen = []
    def handler(request):
        seen.append(json.loads(request.content)["params"]["arguments"])
        return response(request, {"structuredContent": {"results": []}})
    for arguments in ({"limit": 25, "include_facet_counts": True}, {}):
        original = copy.deepcopy(arguments)
        run(lambda m: m.call(name, arguments), handler)
        assert arguments == original
        assert seen[-1]["limit"] == MAX_ITEMS
        assert "include_facet_counts" not in seen[-1]
    assert bounded_arguments("get_paper_info", {"repo_limit": 200})["repo_limit"] == MAX_ITEMS


def test_count_only_opt_in_is_described_stripped_from_upstream_and_has_no_items():
    def handler(request):
        params = json.loads(request.content)
        if params["method"] == "tools/list":
            return response(request, {"tools": [{"name": n, "description": "Original", "inputSchema": {
                "type": "object", "properties": {"limit": {"type": "integer", "maximum": 100, "default": 25}}}} for n in TOOL_NAMES]})
        args = params["params"]["arguments"]
        assert args == {"limit": 1, "include_facet_counts": True, "kind": "post"}
        return response(request, {"structuredContent": {"total": 12, "results": [{"title": "Omit me"}], "facet_counts": {"kind": {"post": 12}}}})
    tools = run(lambda m: m.tools(), handler)
    browse = next(t["function"] for t in tools if t["function"]["name"] == "browse_catalog")
    assert "at most 10" in browse["description"] and "counts_only=true" in browse["description"]
    assert browse["parameters"]["properties"]["limit"]["maximum"] == 10
    assert "counts_only" in browse["parameters"]["properties"]
    result = run(lambda m: m.call("browse_catalog", {"limit": 100, "counts_only": True, "kind": "post"}), handler)
    assert json.loads(result.text) == {"total": 12, "facet_counts": {"kind": {"post": 12}}}


def test_whole_organizations_collection_is_projected_with_counts_total_and_links():
    data = {"count": 120, "results": [{"id": str(i), "name": f"Org {i}", "slug": f"org-{i}",
            "paper_count": i, "post_count": i + 1, "catalog_stars": 100,
            "description": "Unused verbose description " * 150, "logo_url": "https://image.test/long"} for i in range(120)]}
    result = run(lambda m: m.call("list_organizations", {"sort": "papers"}),
                 lambda r: response(r, {"structuredContent": {"schema_version": "v1", "data": data}}))
    payload = json.loads(result.text)
    assert payload["total"] == 120 and payload["returned"] == 10 and payload["items_omitted"]
    assert payload["results"][0] == {"id": "0", "name": "Org 0", "slug": "org-0", "paper_count": 0,
                                      "post_count": 1, "catalog_stars": 100, "catalog_url": "/orgs/org-0"}
    assert result.full_bytes < MAX_RESULT_BYTES and not result.truncated
    assert "topic-specific" in payload["note"]


def test_search_keeps_one_copy_and_short_summaries_even_if_upstream_ignores_limit():
    items = [{"id": str(i + 1), "title": "Post", "abstract": "x" * 10000, "source_url": "https://source.test"} for i in range(25)]
    result = run(lambda m: m.call("search_papers", {}), lambda r: response(r, {"structuredContent": {
        "schema_version": "v1", "data": {"count": 40, "results": items}, "items": items, "next_page": 2}}))
    data = json.loads(result.text)
    assert len(data["results"]) == 10 and data["next_page"] == 2 and data["total"] == 40
    assert "items" not in data and "data" not in data
    assert all(len(item["abstract"]) <= 601 for item in data["results"])
    assert not result.truncated


def test_identical_effective_calls_reuse_the_first_result_without_network_or_evidence_duplication():
    services = FakeServices([
        [tool_chunk(arguments='{"query":"agents","limit":25}')],
        [tool_chunk(arguments='{"limit":100,"query":"agents"}')], [text_chunk("Answer")],
    ])
    turn, _ = asyncio.run(services.run(TurnLimits(tool_calls=2)))
    assert len(services.tool_requests) == 1
    steps = [s for s in turn.steps if s["kind"] == "tool"]
    assert steps[1]["cached_from"] == steps[0]["call_id"]
    assert "reuse that result" in steps[1]["result"]
    assert steps[0]["effective_arguments"] == {"query": "agents", "limit": 10}
    assert len([m for m in services.model_requests[-1]["messages"] if "Catalog tool evidence" in str(m["content"])]) == 1
    assert "reuse that result" not in json.dumps(services.model_requests[-1])


def test_reported_input_budget_stops_research_and_still_finalizes():
    services = FakeServices([[tool_chunk(), chunk(usage={"prompt_tokens": 33000, "completion_tokens": 20, "total_tokens": 33020})], [text_chunk("Limited evidence answer")]])
    turn, _ = asyncio.run(services.run(TurnLimits(input_tokens=96000)))
    assert turn.status == "limit_reached" and turn.text == "Limited evidence answer"
    assert len(services.model_requests) == 2 and "tools" not in services.model_requests[-1]
    assert not services.tool_requests
    assert turn.steps[0]["input_token_charge"] == 33000
    assert not turn.steps[0]["input_tokens_estimated"]
    assert turn.steps[0]["input_token_budget"] == 96000
    assert INPUT_TOKEN_BUDGET == 256000


def test_unknown_usage_is_estimated_and_charged_to_cumulative_budget():
    services = FakeServices([[tool_chunk()], [tool_chunk()], [text_chunk("Final")]])
    turn, _ = asyncio.run(services.run(TurnLimits(input_tokens=20000)))
    model_steps = [s for s in turn.steps if s["kind"] == "model"]
    assert all(s["input_tokens"] is None and s["input_tokens_estimated"] for s in model_steps)
    assert all(s["input_token_charge"] > 0 for s in model_steps)
    assert model_steps[-1]["cumulative_input_tokens"] == sum(s["input_token_charge"] for s in model_steps)
    assert len(services.model_requests) <= 3


def test_finalizer_input_is_bounded_preserves_question_and_marks_shortened_evidence():
    question = "Which organizations publish the most about AI agent sandboxing?"
    history = [{"role": "user", "content": "old " * 10000}, {"role": "assistant", "content": "prior " * 10000}, {"role": "user", "content": question}]
    steps = [{"kind": "tool", "name": "search_papers", "result": "Evidence " * 10000} for _ in range(10)]
    allowance = FINAL_INPUT_TOKENS + history_token_estimate(history)
    messages = finalizer_messages(SYSTEM_PROMPT, FINALIZER_PROMPT, history, steps, allowance)
    assert estimate_input_tokens(messages) <= allowance
    assert messages[1:3] == history[:2]
    assert any(m["content"] == question for m in messages)
    assert "Shortened for input budget" in json.dumps(messages)


def test_reported_cumulative_growth_in_review_trace_goes_to_finalizer_before_fourth_research_call():
    replies = []
    for i, tokens in enumerate((1753, 7546, 24801)):
        replies.append([tool_chunk(arguments=json.dumps({"query": str(i)})), chunk(usage={
            "prompt_tokens": tokens, "completion_tokens": 20, "total_tokens": tokens + 20})])
    services = FakeServices([*replies, [text_chunk("Answer from bounded evidence")]])
    turn, _ = asyncio.run(services.run(TurnLimits(input_tokens=96000)))
    model_steps = [s for s in turn.steps if s["kind"] == "model"]
    assert len(model_steps) == 4 and model_steps[-1]["phase"] == "finalizer"
    assert model_steps[2]["cumulative_input_tokens"] == 34100
    assert model_steps[-1]["cumulative_input_tokens"] < INPUT_TOKEN_BUDGET
    assert model_steps[-1]["input_messages"] == services.model_requests[-1]["messages"]
    assert len(services.tool_requests) == 2


def test_research_budget_is_a_soft_stop_before_the_hard_limit():
    from backend.services.assistant_loop import TurnLimits, research_budget_notice

    limits = TurnLimits()
    assert (limits.tool_calls, limits.soft_tool_calls) == (20, 15)
    sent: set[str] = set()
    assert research_budget_notice(14, limits, sent) is None
    wrap_up = research_budget_notice(15, limits, sent)
    assert "15 of 20" in wrap_up and "wrapping up" in wrap_up
    assert research_budget_notice(16, limits, sent) is None  # said once
    answer_now = research_budget_notice(19, limits, sent)
    assert "19 of 20" in answer_now and "Write your answer now" in answer_now
    assert research_budget_notice(19, limits, sent) is None
    # A batch that jumps past both thresholds gets only the stronger message.
    assert "Write your answer now" in research_budget_notice(19, limits, set())
