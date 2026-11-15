"""Run the fixed catalog evaluation; no chat writes or visitor identity.

Tool results use the same optional read-only post-metadata enrichment as chat.

Usage: uv run --env-file .local.env python -m backend.assistant_eval \
    --model glm-5.3-flash --output .assistant-evals/glm.jsonl
A full evaluation can use up to 240 model requests (including follow-ups). Run only with the owner's
explicit budget authorization, not as an automated test or startup check.
"""

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

import anyio
import httpx
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from backend.assistant_config import AssistantSettings
from backend.services.assistant_loop import Turn, model_client, run_turn
from backend.services.assistant_mcp import CatalogMcp
from backend.services.assistant_topics import UnknownTopic, resolve_topic

TOPIC_QUESTIONS = {
    "Which pentesting posts explain how teams validate an agent's findings?": "penetration-testing",
    "What have defenders learned about attacks on AI agents?": "ai-system-security",
    "Which engineering practices make security agents more reliable?": "security-engineering",
    "How do teams validate agent-generated vulnerability fixes?": "repair",
}

QUESTIONS = (
    "Which posts show cutting-edge harness design for automated pentesting?",
    "How are teams benchmarking AI agents on security tasks, and what did they find?",
    "What do defenders report about ARTEX and other agentic attack frameworks?",
    "How are companies using agents to triage and fix vulnerabilities?",

    "Show me repositories for security research.",
    "What is EVMbench, and where can I read its catalog page?",
    "Find Cybench and summarize what it evaluates, with catalog links.",
    "Find ChatAFL and its official repository in the catalog.",
    *TOPIC_QUESTIONS,
    "Find papers about fuzzing and test generation.",
    "Find research about smart-contract security.",
    "Which catalog repositories have the most stars? Explain what the counts mean.",
    "Pick a listed organization and describe its catalog work with a link to its organization page.",
    "Pick a listed developer and show their tracked repositories and profile link.",
    "Find related work for one recent security paper, citing catalog evidence.",
    "Read the cached text for EVMbench and summarize its evaluation; say if no text is cached.",
    "Find a catalog entry titled ZZZ-Unpublished-Quantum-Toaster-999; say plainly if it is absent.",
)


def result_row(index, question, model, turn, elapsed):
    model_steps = [s for s in turn.steps if s["kind"] in {"model", "follow_ups"}]
    tokens = {}
    for field in ("input_tokens", "output_tokens"):
        values = [s.get(field) for s in model_steps]
        tokens[field] = sum(values) if values and all(v is not None for v in values) else None
    expected = question in TOPIC_QUESTIONS
    follow_ups = turn.follow_ups if turn.status in {"done", "limit_reached"} else []
    follow_up_steps = [s for s in turn.steps if s.get("phase") == "follow_ups" or s["kind"] == "follow_ups"]
    checked = any(s.get("name") == "submit_follow_ups" and not s.get("error") for s in follow_up_steps)
    follow_up_models = [s for s in follow_up_steps if s['kind'] in {'model', 'follow_ups'}]
    return {"question_id": index, "question": question, "model": model,
            "topic": TOPIC_QUESTIONS.get(question), "follow_ups": follow_ups,
            "follow_ups_check": {"expected": expected, "passed": bool(checked and follow_ups) if expected else None},
            "answer": turn.text, "status": turn.status, "error": turn.error,
            "tools": [s for s in turn.steps if s["kind"] == "tool"],
            "follow_up_steps": follow_up_steps,
            "follow_up_tokens": {key: sum(s[key] for s in follow_up_models) if follow_up_models and all(s.get(key) is not None for s in follow_up_models) else None
                                 for key in ('input_tokens', 'output_tokens')},
            "links": sorted(set(re.findall(r"\]\((https?://[^\s)]+|/[^\s)]+)\)", turn.text))),
            "duration_ms": round(elapsed * 1000), "tokens": tokens,
            "model_calls": len(model_steps),
            "research_model_calls": sum(s["kind"] == "model" and s.get('phase') != 'follow_ups' for s in model_steps)}


async def evaluate(client, mcp, model, output, *, questions=QUESTIONS, follow_ups_enabled=None):
    """Write each completed question immediately, stopping if a quota is hit."""
    for index, question in enumerate(questions, 1):
        turn = Turn()
        began = time.monotonic()
        slug = TOPIC_QUESTIONS.get(question)
        topic = await anyio.to_thread.run_sync(resolve_topic, slug, mcp.sessions) if slug else None
        async for _ in run_turn(client, mcp, model, [{"role": "user", "content": question}], turn, topic=topic,
                                follow_ups_enabled=follow_ups_enabled):
            pass
        row = result_row(index, question, model, turn, time.monotonic() - began)
        output.write(json.dumps(row, ensure_ascii=False) + "\n")
        output.flush()
        print(f"Question {index}/{len(questions)}: {turn.status}; {row['duration_ms']} ms", file=sys.stderr)
        if turn.status == "provider_limit" or any(s.get("status") == "usage_limit" for s in row["follow_up_steps"]):
            return False
    return True


async def run(args):
    settings = AssistantSettings()
    if not settings.api_key.get_secret_value():
        print("Set PWC_ASSISTANT_API_KEY in the process environment.", file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents replacing an earlier evaluation accidentally.
    with args.output.open("x", encoding="utf-8") as output:
        async with httpx.AsyncClient(timeout=30) as http, model_client(settings) as client:
            completed = await evaluate(client, CatalogMcp(http, args.mcp_url), args.model, output,
                                       follow_ups_enabled=settings.follow_ups_enabled)
    return 0 if completed else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="Named model; no implicit model selection")
    parser.add_argument("--mcp-url", default="http://localhost:8095/mcp")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        return asyncio.run(run(args))
    except (OSError, httpx.HTTPError, ValidationError, SQLAlchemyError, UnknownTopic):
        print("Evaluation could not finish. Check the local endpoints, database/topic choices and output path.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
