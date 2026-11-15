"""Admission estimates and bounded finalizer context; no extra summarizing model."""

import json
import math

INPUT_TOKEN_BUDGET = 64000
FINAL_INPUT_TOKENS = 16000
FINAL_INPUT_RESERVE = 2 * FINAL_INPUT_TOKENS
MIN_FINAL_INPUT_TOKENS = 2048
CHARS_PER_TOKEN = 3  # Conservative text estimate, not a provider tokenizer.


def estimate_input_tokens(messages, tools=()):
    serialized = json.dumps({"messages": messages, "tools": tools}, ensure_ascii=False, separators=(",", ":"))
    return 64 + 16 * len(messages) + math.ceil(len(serialized) / CHARS_PER_TOKEN)


def finalizer_messages(system, final_prompt, history, steps, token_limit, *, scope_prompt=None):
    # Keep the question, a little recent conversation, and each distinct result.
    # Repeated calls already point at the first result; never duplicate evidence.
    evidence = [{"role": "user", "content": f"Catalog tool evidence ({s['name']}):\n{s['result']}"}
                for s in steps if s["kind"] == "tool" and s["result"] and not s.get("cached_from")]
    question = next((m for m in reversed(history) if m["role"] == "user"), {"role": "user", "content": ""})
    previous = [{"role": m["role"], "content": m["content"][:500]} for m in history[:-1][-4:] if m.get("content")]
    scope = [{"role": "system", "content": scope_prompt}] if scope_prompt else []
    messages = [{"role": "system", "content": system}, *scope, *previous, dict(question),
                *evidence, {"role": "system", "content": final_prompt}]
    # Reduce the longest optional text first; explicit notices prevent treating
    # shortened samples as complete catalog evidence. System/question stay intact.
    optional = [*previous, *evidence]
    while optional and estimate_input_tokens(messages) > token_limit:
        item = max(optional, key=lambda m: len(m["content"]))
        if len(item["content"]) <= 160:
            messages.remove(item)
            optional.remove(item)
        else:
            excess = (estimate_input_tokens(messages) - token_limit) * CHARS_PER_TOKEN
            room = max(80, len(item["content"]) - max(excess, len(item["content"]) // 4))
            item["content"] = item["content"][:room] + "\n[Shortened for input budget; evidence may be incomplete.]"
    return messages
