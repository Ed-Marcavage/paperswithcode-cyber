"""Exercise the EVMbench acceptance case against the running preview, using only HTTP reads."""
import argparse
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from urllib.parse import urlencode


def check(base, expected_count):
    base = base.rstrip("/")
    ref = "2603.04915"

    def get(route):
        with urlopen(base + route, timeout=15) as response:
            return response.read()

    def rpc(method, params, request_id=1):
        body = dict(jsonrpc="2.0", method=method, params=params)
        if request_id is not None:
            body["id"] = request_id
        req = Request(base + "/mcp", data=json.dumps(body).encode(), headers={
            "Content-Type": "application/json", "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-11-25",
        })
        with urlopen(req, timeout=20) as response:
            if request_id is None:
                assert response.status in (200, 202, 204)
                return
            packet = json.load(response)
        assert "error" not in packet, packet.get("error")
        return packet["result"]

    def tool(name, **args):
        result = rpc("tools/call", {"name": name, "arguments": args})
        assert not result.get("isError"), result.get("content")
        return result["structuredContent"]

    assert json.loads(get("/mcp/health"))["status"] == "ok"
    info = rpc("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                              "clientInfo": {"name": "catalog-check", "version": "1"}})
    assert info["protocolVersion"] == "2025-11-25"
    rpc("notifications/initialized", {}, None)
    tools = rpc("tools/list", {})["tools"]
    assert all(t["annotations"]["readOnlyHint"] for t in tools)
    assert {"catalog_filters", "browse_catalog", "read_paper"} <= {t["name"] for t in tools}
    assert {"list_developers", "get_developer"} <= {t["name"] for t in tools}
    # These two views of an alternative must agree: changing a facet, and
    # counting it while the other filters remain selected.
    fields = dict(topic="penetration-testing", contribution="benchmark", limit=3)
    choices = tool("list_developers", **fields, include_facet_counts=True)
    selected_devs = tool("list_developers", **fields, target="networks")
    assert choices["facet_counts"]["target"].get("networks", 0) == selected_devs["count"]
    assert selected_devs == json.loads(get("/api/v1/developers/?" + urlencode({**fields, "target": "networks"})))
    if selected_devs["results"]:
        first = selected_devs["results"][0]
        profile = tool("get_developer", github_id=first["github_id"])
        assert first["featured_repo"] in {r["full_name"] for r in profile["repositories"]}
        team = tool("list_developers", repository=first["featured_repo"], q=first["login"])
        assert first["github_id"] in {r["github_id"] for r in team["results"]}
    terms = tool("catalog_filters")
    assert terms["target"]["smart-contracts"] == "Smart contracts"
    assert tool("browse_catalog")["total"] == expected_count
    selected = tool("browse_catalog", target="smart-contracts", contribution="benchmark")
    work = next(w for w in selected["results"] if w["reference"] == ref)
    assert work == json.loads(get("/api/v1/catalog/papers/" + ref))
    assert work["has_text"] and "dataset" in work["facets"]["contribution"]
    assert work["artifact_url"] == "https://github.com/openai/frontier-evals/tree/main/project/evmbench"
    hit = next(h for h in tool("search_papers", query="EVMbench")["items"] if h["arxiv_id"] == ref)
    assert hit["id"] == work["paper_id"]
    detail = tool("get_paper_info", paper=ref, include_resources=True)
    assert detail["discovery"] == work
    assert any(r["url"].rstrip("/") == "https://github.com/openai/frontier-evals"
               and r["is_official"] for r in detail["paper"]["repositories"])
    assert tool("browse_catalog", target="no-such-target")["total"] == 0
    # Compare every signed MCP chunk with the document the UI actually links to.
    document = get("/api/v1/catalog/papers/" + work["paper_id"] + "/text")
    parts, cursor = [], None
    while True:
        result = tool("read_paper", paper=ref, **({"cursor": cursor} if cursor else {}))
        parts.append(result["markdown"].encode())
        cursor = result["next_cursor"]
        assert bool(cursor) == result["truncated"]
        if not cursor:
            break
        assert len(parts) < 50
    assert len(parts) > 1 and b"".join(parts) == document
    missing = next(w for w in json.loads(get("/api/v1/catalog/papers?limit=100"))["results"] if not w["has_text"])
    note = tool("read_paper", paper=missing["reference"])["markdown"]
    assert "No cached text" in note and missing["source_url"] in note
    try:
        urlopen(Request(base + "/api/v1/catalog/papers", data=b"{}"), timeout=5)
    except HTTPError as exc:
        assert exc.code == 405, exc.code
    else:
        raise AssertionError("Write request was not rejected")
    print(f"{expected_count} papers; {len(tools)} read-only tools; EVMbench matches across UI API and MCP; "
          f"{len(document):,} bytes in {len(parts)} chunks; missing text and write rejection verified.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://localhost:8095")
    parser.add_argument("--expected-count", type=int, default=75)
    args = parser.parse_args()
    check(args.base, args.expected_count)
