"""Admission estimates and bounded finalizer context; no extra summarizing model."""

import json
import math
from backend.services.assistant_context import paired_messages

HISTORY_INPUT_TOKENS = 128000
MAX_CONTEXT_INPUT_TOKENS = 256000
INPUT_TOKEN_BUDGET = 256000  # Cumulative new-turn growth, not replayed history.
FINAL_INPUT_TOKENS = 32000  # New evidence per finalizer, in addition to history.
FINAL_INPUT_RESERVE = 2 * FINAL_INPUT_TOKENS
MIN_FINAL_INPUT_TOKENS = 2048
CHARS_PER_TOKEN = 3  # Conservative text estimate, not a provider tokenizer.


def estimate_input_tokens(messages, tools=()):
    serialized = json.dumps({"messages": messages, "tools": tools}, ensure_ascii=False, separators=(",", ":"))
    return 64 + 16 * len(messages) + math.ceil(len(serialized) / CHARS_PER_TOKEN)


def history_token_estimate(history):
    return max(0, estimate_input_tokens(history[:-1]) - estimate_input_tokens([]))


def growth_charge(reported, full_estimate, history_estimate):
    """Prorate reported usage by estimated new/history shares; retain full usage.

    Subtracting a character estimate directly from real token usage could erase
    all new-token cost when the conservative history estimate is too large.
    """
    new_estimate = max(1, full_estimate - history_estimate)
    return math.ceil(reported * new_estimate / max(1, full_estimate)) if reported is not None else new_estimate


def finalizer_messages(system, final_prompt, history, steps, token_limit, *, scope_prompt=None):
    # Keep the question, a little recent conversation, and each distinct result.
    # Repeated calls already point at the first result; never duplicate evidence.
    evidence = [{"role": "user", "content": f"Catalog tool evidence ({s['name']}):\n{s['result']}"}
                for s in steps if s["kind"] == "tool" and s["result"] and not s.get("cached_from")]
    question = next((m for m in reversed(history) if m["role"] == "user"), {"role": "user", "content": ""})
    previous = paired_messages(history[:-1])
    scope = [{"role": "system", "content": scope_prompt}] if scope_prompt else []
    messages = [{"role": "system", "content": system}, *scope, *previous, dict(question),
                *evidence, {"role": "system", "content": final_prompt}]
    # Reduce the longest optional text first; explicit notices prevent treating
    # shortened samples as complete catalog evidence. System/question stay intact.
    optional = [*evidence]
    while optional and estimate_input_tokens(messages) > token_limit:
        item = max(optional, key=lambda m: len(m["content"]))
        if len(item["content"]) <= 160:
            messages.remove(item)
            optional.remove(item)
        else:
            excess = (estimate_input_tokens(messages) - token_limit) * CHARS_PER_TOKEN
            room = max(80, len(item["content"]) - max(excess, len(item["content"]) // 4))
            item["content"] = item["content"][:room] + "\n[Shortened for input budget; evidence may be incomplete.]"
    if estimate_input_tokens(messages) > token_limit:
        raise ValueError('Protected conversation history exceeds the finalizer allowance.')
    return messages
