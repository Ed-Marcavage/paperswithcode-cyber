import asyncio
import copy
import json
from types import SimpleNamespace

import httpx
from openai import AsyncOpenAI

from backend.services.assistant_loop import SYSTEM_PROMPT, Turn, TurnLimits, run_turn
from backend.services.assistant_mcp import CatalogMcp, TOOL_NAMES
from backend.tests.assistant.test_mcp import FILTERS


def chunk(delta=None, finish=None, usage=None):
    return {"id": "completion", "object": "chat.completion.chunk", "created": 1,
            "model": "fake", "choices": [] if usage else [
                {"index": 0, "delta": delta or {}, "finish_reason": finish}], "usage": usage}


def tool_chunk(index=0, name="search_papers", arguments='{"query":"security"}'):
    return chunk({"tool_calls": [{"index": index, "id": f"call-{index}", "type": "function",
                                  "function": {"name": name, "arguments": arguments}}]})


def text_chunk(text="An answer"):
    return chunk({"content": text})


class FakeServices:
    def __init__(self, replies, *, sessions=None):
        self.replies = iter(replies)
        self.sessions = sessions
        self.model_requests = []
        self.tool_requests = []

    def model(self, request):
        self.model_requests.append(json.loads(request.content))
        reply = next(self.replies)
        if isinstance(reply, httpx.Response):
            return reply
        if isinstance(reply, int):
            return httpx.Response(reply, json={"error": {"message": "private detail", "type": "server_error"}})
        body = "".join("data: " + json.dumps(c) + "\n\n" for c in reply) + "data: [DONE]\n\n"
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    def mcp(self, request):
        payload = json.loads(request.content)
        if payload["method"] == "tools/list":
            result = {"tools": [{"name": name, "inputSchema": {"type": "object"}} for name in TOOL_NAMES]}
        elif payload["params"].get("name") == "catalog_filters":
            result = {"structuredContent": FILTERS}
        else:
            self.tool_requests.append(payload["params"])
            result = {"structuredContent": {"title": "Evidence", "url": "/paper/evidence"}}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"], "result": result})

    async def run(self, limits=TurnLimits(), *, model_name="fake", topic=None, **kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(self.model)) as model_http:
            async with httpx.AsyncClient(transport=httpx.MockTransport(self.mcp)) as mcp_http:
                async with AsyncOpenAI(api_key="fake", base_url="http://model.test/v1", max_retries=0,
                                       http_client=model_http) as model:
                    turn = Turn()
                    events = [event async for event in run_turn(
                        model, CatalogMcp(mcp_http, "http://catalog.test/mcp", sessions=self.sessions), model_name,
                        [{"role": "user", "content": "Find security papers"}], turn, limits=limits, topic=topic, **kwargs)]
                    return turn, events


def test_plain_answer_and_private_request_contract():
    services = FakeServices([[text_chunk(), chunk(finish="stop"), chunk(usage={
        "prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15})]])
    turn, events = asyncio.run(services.run())
    assert turn.text == "An answer"
    assert turn.status == "done"
    assert events[-1] == {"type": "done", "status": "done", "follow_ups": []}
    request = services.model_requests[0]
    assert request["messages"][0]["content"] == SYSTEM_PROMPT
    assert "user" not in request and "tool_choice" not in request
    assert set(request) == {"model", "messages", "stream", "stream_options", "max_tokens", "tools", "reasoning_effort"}
    assert request["stream_options"] == {"include_usage": True}
    assert turn.steps[0]["input_tokens"] == 12


def test_interleaved_tool_calls_and_grounded_answer():
    services = FakeServices([
        [tool_chunk(arguments='{"query":'), tool_chunk(1, "list_organizations", '{}'),
         chunk({"tool_calls": [{"index": 0, "function": {"arguments": '"security"}'}}]}), chunk(finish="tool_calls")],
        [text_chunk("[Evidence](/paper/evidence)"), chunk(finish="stop")],
    ])
    turn, events = asyncio.run(services.run())
    assert turn.status == "done"
    assert len(services.tool_requests) == 2
    assert [e["type"] for e in events] == ["tool_started", "tool_finished", "tool_started", "tool_finished", "text_delta", "answer_complete", "done"]
    messages = services.model_requests[1]["messages"]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "tool", "tool"]
    assert "/paper/evidence" in messages[-1]["content"]
    assert events[3]["result"] == messages[-1]["content"]
    assert turn.steps[0]["input_tokens"] is None


def test_model_turn_limit_reserves_two_passes_for_finalizer():
    services = FakeServices([[tool_chunk()]] * 6 + [[text_chunk("Final answer")]])
    turn, _ = asyncio.run(services.run(TurnLimits(model_turns=8, tool_calls=10, seconds=90)))
    assert turn.status == "limit_reached"
    assert len(services.model_requests) == 7
    assert "tools" not in services.model_requests[-1]
    assert "tool_choice" not in services.model_requests[-1]


def test_tool_limit_including_multi_call_reply():
    services = FakeServices([[tool_chunk(i, arguments=json.dumps({"query": str(i)})) for i in range(12)], [text_chunk("Final")]])
    turn, _ = asyncio.run(services.run(TurnLimits(model_turns=8, tool_calls=10, seconds=90)))
    assert len(services.tool_requests) == 10
    assert len(turn.steps[0]["tool_calls"]) == 12  # trace includes unexecuted calls too
    assert turn.status == "limit_reached"
    assert "tools" not in services.model_requests[-1]


def test_output_cap_and_finalizer():
    services = FakeServices([[text_chunk("x" * 100)], [text_chunk("y" * 100)]])
    turn, _ = asyncio.run(services.run(TurnLimits(output_chars=40, final_chars=10)))
    assert turn.text == "y" * 10
    assert sum(len(s["text"]) for s in turn.steps if s["kind"] == "model") == 40
    assert turn.status == "limit_reached"
    assert "tools" not in services.model_requests[-1]


def test_empty_finalizer_still_gives_a_bounded_plain_answer():
    services = FakeServices([[tool_chunk()]] * 6 + [[chunk(finish="length")]] * 2)
    turn, events = asyncio.run(services.run(TurnLimits(model_turns=8, tool_calls=10, seconds=90)))
    assert turn.status == "limit_reached"
    assert "narrow your question" in turn.text
    assert len(turn.text) <= TurnLimits().output_chars
    assert events[-3]["type"] == "text_delta"


def test_time_limit_stops_research_and_finalizes_with_tools_off():
    class SlowCatalog:
        async def tools(self):
            await asyncio.sleep(1)

    class Model:
        def __init__(self):
            self.requests = []
            self.chat = SimpleNamespace(completions=self)

        async def create(self, **kwargs):
            self.requests.append(copy.deepcopy(kwargs))
            return Stream()

    class Stream:
        def __aiter__(self):
            async def items():
                from openai.types.chat import ChatCompletionChunk
                yield ChatCompletionChunk.model_validate(text_chunk("Final"))
            return items()

        async def close(self):
            pass

    async def go():
        model = Model()
        turn = Turn()
        events = [e async for e in run_turn(model, SlowCatalog(), "fake", [], turn,
                  limits=TurnLimits(seconds=.1, final_seconds=.08))]
        return model, turn, events

    model, turn, _ = asyncio.run(go())
    assert turn.text == "Final"
    assert turn.status == "limit_reached"
    assert len(model.requests) == 1 and "tools" not in model.requests[0]


def test_provider_error_is_plain_and_working_notes_are_not_answers():
    services = FakeServices([[text_chunk("Started"), tool_chunk()], 500])
    turn, events = asyncio.run(services.run())
    assert turn.text == ""
    assert events[0] == {"type": "working_note", "text": "Started"}
    assert turn.steps[0]["text"] == "Started"
    assert turn.status == "failed"
    assert events[-1]["type"] == "error"
    assert "private" not in json.dumps(events)


def test_bad_arguments_and_disallowed_tools_are_never_sent_to_mcp():
    services = FakeServices([[tool_chunk(arguments='[]'), tool_chunk(1, "delete_paper")], [text_chunk("Could not find evidence")]])
    turn, _ = asyncio.run(services.run())
    assert services.tool_requests == []
    assert len([step for step in turn.steps if step["kind"] == "tool" and step["error"]]) == 2


def test_working_notes_are_separate_from_answer_and_model_history():
    note = "Let me also check the engineering posts."
    services = FakeServices([
        [text_chunk("Let me also check "), text_chunk("the engineering posts."), tool_chunk()],
        [text_chunk("The final answer."), chunk(finish="stop")],
    ])
    turn, events = asyncio.run(services.run())
    assert events[0] == {"type": "working_note", "text": note}
    assert [e["text"] for e in events if e["type"] == "text_delta"] == ["The final answer."]
    assert turn.text == "The final answer."
    assert turn.steps[0]["text"] == note
    assert services.model_requests[1]["messages"][2]["content"] is None
    assert note not in json.dumps(services.model_requests[1])


def test_working_notes_use_output_budget_but_not_finalizer_history():
    services = FakeServices([[text_chunk("working"), tool_chunk()], [text_chunk("answer")]])
    turn, events = asyncio.run(services.run(TurnLimits(tool_calls=1)))
    assert turn.text == "answer" and turn.status == "limit_reached"
    assert events[0] == {"type": "working_note", "text": "working"}
    assert "working" not in json.dumps(services.model_requests[-1])
    assert "tools" not in services.model_requests[-1]


def test_prompt_leaves_link_style_to_the_model_but_forbids_invented_addresses():
    from backend.services.assistant_loop import PROMPT_VERSION
    assert PROMPT_VERSION == "cyber-assistant-v12"
    assert "catalog_url" not in SYSTEM_PROMPT
    assert "Use only addresses present in tool results and never invent one" in SYSTEM_PROMPT
