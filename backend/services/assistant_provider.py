"""Classify Ollama quota exhaustion separately from temporary concurrency.

Evidence: docs.ollama.com/api/errors and first-hand error reports at
github.com/NousResearch/hermes-agent/issues/68831 (session),
github.com/diegosouzapw/OmniRoute/issues/7071 (session/weekly).
The live /api/balance schema was checked on 2026-11-14. It supplies
included.{session,weekly}.resets_at; no inference call is needed to read it.
"""

import re
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import httpx

USAGE_LIMIT_MESSAGE = "The assistant is resting. It has reached its usage limit and will be back later."


def error_message(error) -> str:
    body = error.body
    if isinstance(body, dict):
        body = body.get("error", body)
    if isinstance(body, dict):
        body = body.get("message", "")
    return body if isinstance(body, str) else ""


def is_usage_limit(error) -> bool:
    message = error_message(error).lower()
    return any(phrase in message for phrase in (
        "session usage limit", "weekly usage limit", "monthly usage limit",
        "usage limit exceeded", "quota exceeded", "insufficient_quota", "quota exhausted",
    ))


def is_busy(error) -> bool:
    return "too many concurrent requests" in error_message(error).lower() and not is_usage_limit(error)


def reset_timestamp(value, now):
    try:
        if isinstance(value, (int, float)):
            reset = datetime.fromtimestamp(value, UTC)
        elif isinstance(value, str):
            reset = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            return None
        if reset.tzinfo is None:
            return None
        return reset.astimezone(UTC) if reset > now else None
    except (ValueError, OverflowError, OSError):
        return None


def reset_from_error(error, now):
    body = error.body
    if isinstance(body, dict):
        body = body.get("error", body)
    if isinstance(body, dict):
        reset = reset_timestamp(body.get("resets_at"), now)
        if reset:
            return reset
    response = getattr(error, "response", None)
    retry = response.headers.get("retry-after") if response is not None else None
    if retry:
        try:
            return now + timedelta(seconds=max(1, float(retry)))
        except (ValueError, OverflowError):
            try:
                return reset_timestamp(parsedate_to_datetime(retry).timestamp(), now)
            except (ValueError, TypeError, OverflowError):
                pass
    return None


async def quota_reset(error, settings, *, client=None, now=None):
    now = now or datetime.now(UTC)
    reset = reset_from_error(error, now)
    if reset:
        return reset
    message = error_message(error).lower()
    window = next((w for w in ("weekly", "session", "monthly") if f"{w} usage limit" in message), None)
    # Only Ollama cloud implements this metadata API. Never send this key to
    # a guessed endpoint when an operator configures a different provider.
    base = urlsplit(settings.base_url)
    if window and base.scheme == "https" and base.netloc == "ollama.com":
        async def read(http):
            try:
                response = await http.get("https://ollama.com/api/balance", timeout=3,
                                          headers={"Authorization": "Bearer " + settings.api_key.get_secret_value()})
                if response.status_code == 200:
                    body = response.json()
                    included = body.get("included", {}) if isinstance(body, dict) else {}
                    balance = included.get(window, {}) if isinstance(included, dict) else {}
                    if isinstance(balance, dict):
                        return reset_timestamp(balance.get("resets_at"), now)
            except (httpx.HTTPError, ValueError):
                pass  # The configured cooldown is the explicit fallback.
            return None
        if client is not None:
            reset = await read(client)
        else:
            async with httpx.AsyncClient() as http:
                reset = await read(http)
    return reset or now + timedelta(minutes=settings.limit_cooldown_minutes)


def safe_provider_message(error, api_key: str) -> str:
    message = error_message(error)
    if api_key:
        message = message.replace(api_key, "[redacted]")
    # Account handles and opaque credentials do not help explain a limit.
    message = re.sub(r"you \([^)]*\)", "you ([account])", message, flags=re.I)
    message = re.sub(r"(?i)bearer\s+\S+", "Bearer [redacted]", message)
    return message[:2000]
