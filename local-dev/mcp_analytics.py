"""Best-effort named tool counts; requests never wait for the analytics service."""

import asyncio
import json
import os
import urllib.error
import urllib.request

_pending: set[asyncio.Task] = set()


def _post(url: str, body: bytes) -> None:
    try:
        request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=3):
            pass
    except (OSError, urllib.error.URLError):
        pass  # Existing operational request logs remain available when capture fails.


def capture_tool(tool: str, status: int) -> None:
    token = os.environ.get("PWC_POSTHOG_PROJECT_TOKEN")
    host = os.environ.get("PWC_POSTHOG_HOST", "https://us.i.posthog.com")
    if not token or host not in {"https://us.i.posthog.com", "https://eu.i.posthog.com"} or len(_pending) >= 8:
        return
    body = json.dumps({
        "api_key": token, "event": "catalog_mcp_tool_called",
        "properties": {"distinct_id": "catalog-mcp-service", "tool": tool, "http_status": status,
                       "catalog_environment": os.environ.get("CATALOG_ANALYTICS_ENV", "preview"),
                       "$process_person_profile": False, "$geoip_disable": True},
    }).encode()
    task = asyncio.create_task(asyncio.to_thread(_post, host + "/i/v0/e/", body))
    _pending.add(task)
    task.add_done_callback(_pending.discard)
