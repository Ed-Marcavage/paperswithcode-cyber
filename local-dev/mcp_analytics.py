"""Best-effort anonymous MCP software counts; never retain a peer identity."""

import asyncio
import ipaddress
import json
import os
import re
import urllib.error
import urllib.request

from mcp.types import CLIENT_INFO_META_KEY

_pending: set[asyncio.Task] = set()
EVENTS = {"initialize": "catalog_mcp_client_initialized", "tools/list": "catalog_mcp_tools_listed",
          "tools/call": "catalog_mcp_tool_called"}
PROTOCOLS = {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25", "2026-07-28", "legacy", "unknown"}


def label(value, maximum):
    if not isinstance(value, str) or not value.strip():
        return None
    # Reject the entire value, including forbidden characters past the cap.
    if not re.fullmatch(r"[A-Za-z0-9._ -]+", value):
        return "other"
    for token in re.findall(r"(?<![0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9])", value):
        try:
            ipaddress.ip_address(token)
        except ValueError:
            continue
        return "other"
    try:
        ipaddress.ip_address(value.strip())
    except ValueError:
        return value.strip()[:maximum]
    return "other"


def request_properties(payload, headers, *, first_party=False):
    """Only protocol-declared software labels; no arguments, IDs or peer data."""
    params = payload.get("params")
    params = params if isinstance(params, dict) else {}
    meta = params.get("_meta")
    info = params.get("clientInfo") if payload.get("method") == "initialize" else (
        meta.get(CLIENT_INFO_META_KEY) if isinstance(meta, dict) else None)
    info = info if isinstance(info, dict) else {}
    properties = {"client_source": "request" if info else "none"}
    for key, field, cap in (("client_name", "name", 64), ("client_version", "version", 32)):
        if value := label(info.get(field), cap):
            properties[key] = value
    # Only the first product token; comments and later products are discarded.
    ua = headers.get("user-agent", "").split(maxsplit=1)
    if ua:
        product, slash, version = ua[0].partition("/")
        if value := label(product, 64):
            properties["user_agent_product"] = value
        if slash and (value := label(version, 32)):
            properties["user_agent_version"] = value
    if first_party:
        properties["first_party_assistant"] = True
    return properties


def observe_request(state, body, headers, known_tools, *, first_party=False):
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, ValueError):
        return
    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
        return
    method = payload.get("method")
    if not isinstance(method, str) or method not in EVENTS:
        return
    properties = request_properties(payload, headers, first_party=first_party)
    if method == "tools/call":
        params = payload.get("params")
        tool = params.get("name") if isinstance(params, dict) else None
        if not isinstance(tool, str) or tool not in known_tools:
            return
        properties["tool"] = tool
    state["catalog_analytics"] = (EVENTS[method], properties)


def _post(url: str, body: bytes) -> None:
    try:
        request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=3):
            pass
    except (OSError, urllib.error.URLError):
        pass


def capture_request(state, status, protocol):
    token = os.environ.get("PWC_POSTHOG_PROJECT_TOKEN")
    host = os.environ.get("PWC_POSTHOG_HOST", "https://us.i.posthog.com")
    event = state.get("catalog_analytics")
    if not token or not event or host not in {"https://us.i.posthog.com", "https://eu.i.posthog.com"} or len(_pending) >= 8:
        return
    name, caller = event
    body = json.dumps({"api_key": token, "event": name, "properties": {
        "distinct_id": "catalog-mcp-service", **caller, "http_status": status,
        "mcp_protocol": protocol if protocol in PROTOCOLS else "unknown",
        "catalog_environment": (os.environ.get("CATALOG_ANALYTICS_ENV", "preview")
                                if os.environ.get("CATALOG_ANALYTICS_ENV", "preview") in {"preview", "production", "staging"} else "other"),
        "$process_person_profile": False, "$geoip_disable": True,
    }}).encode()
    task = asyncio.create_task(asyncio.to_thread(_post, host + "/i/v0/e/", body))
    _pending.add(task)
    task.add_done_callback(_pending.discard)
