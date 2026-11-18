"""Cyber catalog tools and public result projection, layered over the pinned base server."""

from __future__ import annotations

import json
import re
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent
from pwc_cli.transport import SITE_URL, ResponseError, TransportError
from pydantic import Field

MAX_ROWS = 25
SUMMARY_CHARS = 600
Limit = Annotated[int, Field(ge=1, le=MAX_ROWS)]
Offset = Annotated[int, Field(ge=0, le=2500)]
Slug = Annotated[str, Field(max_length=100)]
PROFILE_TOOLS = {"catalog_filters", "browse_catalog", "find_posts", "list_developers", "get_developer"}
TOOL_ORDER = ("find_posts", "browse_catalog", "search_papers", "catalog_filters", "get_paper_info", "read_paper",
              "list_developers", "get_developer", "list_organizations", "get_organization")
PROFILE_BOUND_TOOLS = PROFILE_TOOLS | {"list_organizations", "list_conferences", "list_frameworks", "get_paper_lineage"}
WORK_FIELDS = {"id", "title", "published", "summary", "publisher", "agent_relevance", "post_type", "tier", "kind",
               "catalog_url", "source_url", "technical_depth", "originality", "harness_engineering", "caveat",
               "subtopics", "citation_count", "has_official_implementation", "code_repository_count",
               "repository", "repositories"}
ORG_FIELDS = {"id", "name", "slug", "website_url", "github_url", "paper_count", "post_count", "agent_post_count",
              "repository_count", "owned_repository_count", "catalog_stars", "catalog_url", "top_trending_paper"}
AXES = {"browse_catalog": ("topic", "target", "contribution", "kind", "year"),
        "find_posts": ("topic",), "list_developers": ("topic", "target", "contribution")}
POST_TYPES = ("benchmark-or-evaluation", "detection-engineering", "engineering-practice", "explainer-or-tutorial",
              "exploit-walkthrough", "incident-postmortem", "malware-or-threat-intel", "opinion-or-strategy",
              "other", "research-summary", "tool-or-release", "vulnerability-writeup")
INSTRUCTIONS = """Public, anonymous, read-only Cyber security catalog. Start with find_posts for industry posts:
engineering practice, agent harnesses, benchmark findings, defender reports and vulnerability triage.
Use browse_catalog or search_papers for papers/repositories; list_developers/get_developer for people;
list_organizations/get_organization for publishers; catalog_filters for vocabulary. Each facet takes one
slug, never an array. Reviewed agent_relevance is 0–4: 3+ usually suits security-agent builders; omit
browse_catalog's filter or use 0 for general vulnerability, malware or threat questions. find_posts
starts at 3 and discloses sparse-search relaxations. Results include absolute catalog_url links;
posts include publisher, summary, date when known, relevance, type and tier. Empty narrow searches
do not establish missing coverage: follow the hint. Lists default to 10–25 rows, maximum 25
(find_posts 10); use paging. Dates are YYYY-MM-DD. Code marked official is catalog-designated,
not independently audited. Developer contributions do not establish paper authorship.
Taxonomy, benchmark, conference and framework tools are inherited from the base server and sparse in this catalog."""
WORK_DESCRIPTION = " Works use id (pass to get_paper_info/read_paper), published, summary, catalog_url and source_url."
POST_DESCRIPTION = (" Posts contain publisher, summary, catalog_url, "
                    "publication date when known, agent_relevance, post_type and tier. "
                    "min_agent_relevance: 0–4; 3+ for security-agent builders, 0 for general threats/malware/vulnerabilities. ")


def one(value, field, choices=None):
    if isinstance(value, str):
        value = value.strip()
        if value.startswith("["):
            try:
                value = json.loads(value)
            except ValueError:
                pass
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
    if isinstance(value, str):
        value = value.strip()
    if not isinstance(value, str) or (value and choices is not None and value not in choices):
        valid = ", ".join(choices) if choices else "call catalog_filters for current values"
        raise ToolError(f"{field} accepts one value, never several values or an array. Valid values: {valid}; or omit.")
    return value


def short(value):
    return value[:SUMMARY_CHARS] + "…" if isinstance(value, str) and len(value) > SUMMARY_CHARS else value


def work_reference(item):
    if not isinstance(item, dict) or item.get("in_catalog") is False:
        return None
    if "title" in item or isinstance(item.get("paper"), str):
        for field in ("paper_id", "id", "reference", "arxiv_id", "paper"):
            value = str(item.get(field, ""))
            if re.fullmatch(r"[1-9][0-9]*|[0-9]{4}\.[0-9]{4,5}(?:v[0-9]+)?", value):
                return re.sub(r"v[0-9]+$", "", value)
    return None


def repo_url(item):
    owner, name = item.get("owner"), item.get("name")
    full = item.get("full_name")
    if not full and isinstance(item.get("url"), str):
        try:
            url = urlsplit(item["url"])
            if url.scheme == "https" and url.netloc == "github.com" and not url.query and not url.fragment:
                full = url.path.strip("/")
        except ValueError:
            pass
    if (not owner or not name) and isinstance(full, str) and full.count("/") == 1:
        owner, name = full.split("/")
    if (isinstance(owner, str) and re.fullmatch(r"[A-Za-z0-9-]+", owner) and isinstance(name, str)
            and re.fullmatch(r"[A-Za-z0-9_.-]+", name) and name not in {".", ".."}):
        return f"{SITE_URL}/repos/{owner}/{name}"
    return None


def project(value, metadata, *, entity="", list_row=False):
    if isinstance(value, list):
        return [project(v, metadata, entity=entity, list_row=True) for v in value[:MAX_ROWS]]
    if not isinstance(value, dict):
        return short(value) if list_row else value
    item = dict(value)
    ref = work_reference(item)
    if ref:
        item.update(metadata.get(ref, {}))
        ref = work_reference(item) or ref
        item["catalog_url"] = f"{SITE_URL}/paper/{ref}"
    post = item.pop("post", None)
    if isinstance(post, dict) or "post" in (item.get("facets") or {}).get("kind", []):
        post = post or {}
        item.update({key: item.get(key, post.get(key)) for key in ("publisher", "agent_relevance", "post_type", "tier")})
        # The API's publisher already resolves linked organization -> mapped/raw host.
        # Match find_posts' curated-company-first filtering without changing the site API.
        if isinstance(post.get("curated_company"), str) and post["curated_company"].strip():
            item["publisher"] = post["curated_company"].strip()
        item["summary"] = short(item.get("summary") or post.get("tldr") or item.get("tldr"))
    if ref and "title" in item:
        item["id"] = ref
        item["published"] = item.get("published") or item.get("date_published")
        if isinstance(item["published"], str) and re.match(r"^\d{4}-\d{2}-\d{2}", item["published"]):
            item["published"] = item["published"][:10]
        item["summary"] = short(item.get("summary") or item.get("tldr") or item.get("abstract"))
        item["source_url"] = item.get("source_url") or item.get("url_abs") or item.get("url")
        kinds = (item.get("facets") or {}).get("kind", [])
        if kinds:
            item["kind"] = kinds[0]
        elif item.get("post_type"):
            item["kind"] = "post"
        for key in ("paper_id", "reference", "arxiv_id", "date_published", "tldr"):
            item.pop(key, None)
        if list_row:
            item = {key: child for key, child in item.items() if key in WORK_FIELDS}
    if entity == "organization" and isinstance(item.get("slug"), str) and re.fullmatch(r"[A-Za-z0-9_-]+", item["slug"]):
        item["catalog_url"] = f"{SITE_URL}/orgs/{item['slug']}"
    if re.fullmatch(r"[1-9][0-9]{0,17}", str(item.get("github_id", ""))):
        item["catalog_url"] = f"{SITE_URL}/developers/{item['github_id']}"
    if url := repo_url(item):
        item["catalog_url"] = url
    if entity == "organization" and list_row:
        item = {key: child for key, child in item.items() if key in ORG_FIELDS}
        if isinstance(item.get("top_trending_paper"), dict):
            top = item["top_trending_paper"]
            link = work_reference(top)
            item["top_trending_paper"] = {"title": short(top.get("title")),
                                           "catalog_url": f"{SITE_URL}/paper/{link}" if link else top.get("catalog_url")}
    # Keep API ids, counts and evidence, but omit bulky ancillary objects in lists.
    if list_row:
        for key in ("created_at", "updated_at", "logo_url", "hf_url", "original_title", "entities",
                    "curated_pin", "display_order", "hf_slug", "has_text"):
            item.pop(key, None)
    for key, child in list(item.items()):
        if isinstance(child, list) and len(child) > MAX_ROWS:
            item[key + "_total"] = len(child)
        if key not in {"markdown", "next_cursor", "catalog_url", "source_url", "url", "url_abs", "artifact_url"}:
            item[key] = project(child, metadata, entity=entity if key in {"data", "results", "items"} else "",
                                list_row=list_row or key == "top_trending_paper")
    return {key: child for key, child in item.items() if child is not None} if list_row else item


def references(value):
    if isinstance(value, list):
        for row in value[:MAX_ROWS]:
            yield from references(row)
    elif isinstance(value, dict) and value.get("in_catalog") is not False:
        if (ref := work_reference(value)) and "post" not in value:
            yield ref
        for key, child in value.items():
            if key not in {"post", "facets"} and isinstance(child, (list, dict)):
                yield from references(child)


def empty_hint(payload, arguments, name):
    base = payload.get("data", payload)
    if not isinstance(base, dict):
        return payload
    rows = base.get("results", base.get("items"))
    if rows != []:
        return payload
    if arguments.get("offset") or arguments.get("page", 1) > 1:
        hint = "Reset offset to 0 or page to 1 first; this page may be past the matches."
    else:
        field = next((k for k in ("query", "search", "subtopic", "publisher", "post_type", "contribution", "target",
                                  "year", "published_after", "topic", "tier", "kind", "repository", "q") if arguments.get(k)), None)
        hint = f"Loosen or remove {field} first." if field else "Try min_agent_relevance=0 or omit harness_engineering."
    base.setdefault("message", "Zero matches under these filters does not mean the catalog has no coverage.")
    base.setdefault("hint", hint)
    return payload


def json_result(payload):
    """One compact JSON document; clients including the assistant parse this text."""
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, separators=(",", ":")))])


class CyberServer(MCPServer):
    """Apply the Cyber profile at the SDK's public call/list extension points."""

    async def list_tools(self):
        tools = await super().list_tools()
        self.input_schemas = {tool.name: tool.input_schema for tool in tools}
        for tool in tools:
            # Profile projection adds metadata/links beyond the base CLI models.
            tool.output_schema = None
            props = tool.input_schema.get("properties", {})
            desc = tool.description or ""
            if "limit" in props:
                desc += f" Page size defaults to {props['limit'].get('default') or 25}; maximum {props['limit'].get('maximum', 25)}."
            if tool.name in AXES:
                desc += " One slug per filter, never arrays. "
                for axis in AXES[tool.name]:
                    values = self.vocabulary.get(axis)
                    years = [value for value in values or [] if re.fullmatch(r"\d{4}", value)] if axis == "year" else []
                    if years:
                        desc += f"year: one four-digit year, {min(years)}–{max(years)}. "
                    else:
                        desc += f"{axis}: {', '.join(values) if values else 'call catalog_filters for current values'}. "
            if tool.name in {"browse_catalog", "find_posts"}:
                desc += POST_DESCRIPTION + "tier: featured, catalog. post_type: " + ", ".join(POST_TYPES) + "."
                if tool.name == "browse_catalog":
                    desc += " Prefer find_posts for industry posts."
            if tool.name in {"browse_catalog", "find_posts", "search_papers", "list_papers", "list_recent_papers",
                             "list_trending_papers", "get_related_papers", "get_paper_lineage", "get_paper_info"}:
                desc += WORK_DESCRIPTION
            for field, spec in props.items():
                variants = [spec, *spec.get("anyOf", [])]
                valid = next((v["enum"] for v in variants if "enum" in v), None)
                if valid and field not in {"sort", "tier", "post_type"}:
                    desc += f" {field}: {', '.join(map(str, valid))}."
            tool.description = " ".join(desc.split())
        return sorted(tools, key=lambda tool: TOOL_ORDER.index(tool.name) if tool.name in TOOL_ORDER else len(TOOL_ORDER))

    async def call_tool(self, name, arguments, context=None):
        args = dict(arguments)
        if self.input_schemas is None:
            self.input_schemas = {tool.name: tool.input_schema for tool in await super().list_tools()}
        schema = self.input_schemas.get(name, {})
        if name in PROFILE_BOUND_TOOLS:
            for field, spec in schema.get("properties", {}).items():
                numeric = next((v for v in [spec, *spec.get("anyOf", [])] if v.get("type") == "integer"), None)
                if numeric and any(key in numeric for key in ("minimum", "exclusiveMinimum", "maximum")) and field in args and args[field] is not None:
                    low = numeric.get("minimum", numeric.get("exclusiveMinimum", -1) + 1)
                    high = numeric.get("maximum")
                    if type(args[field]) is not int or args[field] < low or (high is not None and args[field] > high):
                        allowed = f"{low}–{high}" if high is not None else f"an integer at least {low}"
                        raise ToolError(f"{field} accepts {allowed}.")
        if any(args.get(axis) and axis not in self.vocabulary for axis in AXES.get(name, ())):
            try:
                vocabulary = await anyio.to_thread.run_sync(lambda: self.catalog.discovery("filters"))
                self.vocabulary = {key: sorted(values) for key, values in vocabulary.items() if isinstance(values, dict)}
            except (ResponseError, TransportError):
                raise ToolError("Filter vocabulary is temporarily unavailable; call catalog_filters and retry.") from None
        for field in AXES.get(name, ()):
            if field in args:
                args[field] = one(args[field], field, self.vocabulary.get(field))
        for field, valid in (("post_type", POST_TYPES), ("tier", ("featured", "catalog"))):
            if name in {"browse_catalog", "find_posts"} and field in args:
                args[field] = one(args[field], field, valid)
        for field in (("subtopic", "publisher") if name == "find_posts" else ("repository",) if name == "list_developers" else ()):
            if field in args:
                args[field] = one(args[field], field)
        # Native Literal validation already names enums; normalize their string-array spelling too.
        for field, spec in schema.get("properties", {}).items():
            valid = next((v["enum"] for v in [spec, *spec.get("anyOf", [])] if "enum" in v), None)
            if field in args and args[field] is not None and valid:
                args[field] = one(args[field], field, valid)
            maximum = next((v["maxLength"] for v in [spec, *spec.get("anyOf", [])] if "maxLength" in v), None)
            if name in PROFILE_BOUND_TOOLS and maximum and isinstance(args.get(field), str) and len(args[field]) > maximum:
                raise ToolError(f"{field} accepts at most {maximum} characters.")
        implicit_relevance = name == "find_posts" and "min_agent_relevance" not in args
        if implicit_relevance:
            args["min_agent_relevance"] = None
        result = await super().call_tool(name, args, context)
        # Base catalogs without the Cyber HTTP endpoints retain their native results.
        if not hasattr(self.catalog, "discovery"):
            return result
        if not isinstance(result, CallToolResult) or result.is_error or result.structured_content is None:
            return result
        payload = result.structured_content
        if not isinstance(payload, dict):
            return result
        if name == "catalog_filters":
            return json_result(payload)
        if name == "read_paper" and payload.get("in_catalog") is not False and not work_reference(payload):
            payload["reference"] = await anyio.to_thread.run_sync(self.catalog.resolve_paper, args["paper"])
        if name == "list_tasks" and args.get("group_by_area"):
            groups = payload.get("data", {}).get("results", [])
            rows = [dict(task, area={"id": group.get("id"), "name": group.get("name")})
                    for group in groups for task in group.get("tasks", [])]
            size = args.get("limit") or MAX_ROWS
            payload["data"] = page({"results": rows}, size, (args.get("page", 1) - 1) * size)
        # Typed native pages duplicate rows in data. Keep the compact typed collection.
        if isinstance(payload.get("items"), list):
            data = payload.get("data")
            if isinstance(data, dict):
                payload["total"] = data.get("total", data.get("count", len(payload["items"])))
            else:
                payload.setdefault("total", len(payload["items"]))
            if name == "list_benchmarks" and isinstance(data, dict) and any("tasks" in row for row in data.get("results", [])):
                size = args.get("limit") or MAX_ROWS
                start = (args.get("page", 1) - 1) * size
                payload["total"] = len(payload["items"])
                payload["items"] = payload["items"][start:start + size]
                payload["next_page"] = args.get("page", 1) + 1 if start + size < payload["total"] else None
            if isinstance(data, list):
                # Bare feed endpoints report only the received collection, not a matching total.
                # Keeping data as a list preserves the assistant adapter's count semantics.
                payload["data"] = payload.pop("items")
                payload["total_scope"] = "received_items"
            else:
                payload.pop("data", None)
        elif name in {"get_paper_info", "get_paper_lineage"}:
            payload.pop("data", None)
        if name == "get_paper_lineage":
            size, offset = args.get("limit", 10), args.get("offset", 0)
            for key in ("predecessors", "successors"):
                rows = payload.get(key, [])
                payload[key + "_total"] = len(rows)
                payload[key] = rows[offset:offset + size]
            payload["total"] = payload["predecessors_total"] + payload["successors_total"]
        data = payload.get("data")
        if isinstance(data, dict) and isinstance(data.get("results"), list):
            data.setdefault("total", data.get("count", len(data["results"])))
        metadata = {}
        # Post search is already complete; organization list teasers need only a link.
        refs = [] if name in {"find_posts", "list_organizations"} else list(dict.fromkeys(references(payload)))
        if refs and hasattr(self.catalog, "discovery"):
            try:
                for start in range(0, len(refs), MAX_ROWS):
                    batch = refs[start:start + MAX_ROWS]
                    raw = await anyio.to_thread.run_sync(lambda batch=batch: self.catalog.discovery("metadata", {"references": ",".join(batch)}))
                    for row in raw.get("results", []):
                        for field in ("reference", "paper_id"):
                            if row.get(field):
                                metadata[str(row[field])] = row
            except (ResponseError, TransportError):
                payload["metadata_status"] = "unavailable"
                payload["metadata_note"] = "Post fields may be missing because catalog metadata is temporarily unavailable."
        entity = "organization" if name in {"list_organizations", "get_organization"} else ""
        payload = empty_hint(project(payload, metadata, entity=entity), args, name)
        return json_result(payload)


def page(data, limit, offset):
    rows = data.get("results", [])
    return {**data, "total": data.get("total", data.get("count", len(rows))),
            "results": rows[offset:offset + limit], "limit": limit, "offset": offset}


def register_profile(server, catalog, run, annotations):
    server.catalog = catalog
    server.vocabulary = {}
    server.input_schemas = None
    if hasattr(catalog, "profile_vocabulary"):
        server.vocabulary = catalog.profile_vocabulary()

    @server.tool(annotations=annotations)
    def catalog_filters() -> dict[str, Any]:
        """List current topic, target, contribution, kind and year vocabulary; labels accompany slugs."""
        data = catalog.discovery("filters")
        server.vocabulary = {key: sorted(values) for key, values in data.items() if isinstance(values, dict)}
        return data

    @server.tool(annotations=annotations)
    def browse_catalog(topic: Slug = "", target: Slug = "", contribution: Slug = "", year: Slug = "", kind: Slug = "",
                       limit: Limit = 10, offset: Offset = 0, include_facet_counts: bool = False,
                       min_agent_relevance: Annotated[int, Field(ge=0, le=4)] | None = None,
                       tier: str = "", post_type: Annotated[str, Field(max_length=64)] = "") -> dict[str, Any]:
        """Browse papers, repositories and posts matching all filters. Counts are optional. Empty results include a filter-loosening hint. Omitted relevance allows general reporting."""
        return catalog.discovery("papers", dict(topic=topic, target=target, contribution=contribution, year=year,
            kind=kind, limit=limit, offset=offset, include_facet_counts=include_facet_counts,
            min_agent_relevance=min_agent_relevance, tier=tier, post_type=post_type))

    @server.tool(annotations=annotations)
    def find_posts(query: Annotated[str, Field(max_length=200)] = "", topic: Slug = "", subtopic: Slug = "",
                   post_type: Annotated[str, Field(max_length=64)] = "", tier: str = "",
                   publisher: Annotated[str, Field(max_length=160)] = "",
                   min_agent_relevance: Annotated[int, Field(ge=0, le=4)] | None = 3,
                   harness_engineering: bool | None = None,
                   published_after: Annotated[str, Field(max_length=10)] | None = None,
                   sort: Literal["score", "recent", "score_recent"] = "score",
                   limit: Annotated[int, Field(ge=1, le=10)] = 10) -> dict[str, Any]:
        """Start here for industry posts: engineering practice, agent harnesses, benchmark findings, defender reports, vulnerability triage. Keywords search titles/summaries with English stemming. Sparse searches disclose removal of implicit relevance 3, then ranked any-word matching; explicit relevance is kept. Prefer topic/type without query when sufficient. subtopic is an exact case-insensitive reviewed name; publisher is the name shown in results (e.g. Trail of Bits), case-insensitive; list_organizations lists publishers. Omit names if unknown. published_after is exclusive YYYY-MM-DD. sort: score (depth+originality+harness bonus), recent, score_recent (7-day decay)."""
        params = dict(query=query, topic=topic, subtopic=subtopic, post_type=post_type, tier=tier, publisher=publisher,
                      harness_engineering=harness_engineering, published_after=published_after, sort=sort, limit=limit)
        if min_agent_relevance is not None:
            params["min_agent_relevance"] = min_agent_relevance
        return catalog.discovery("posts", params)

    @server.tool(annotations=annotations)
    def list_developers(q: Annotated[str, Field(max_length=100)] = "", topic: Slug = "", target: Slug = "",
                        contribution: Slug = "", repository: Annotated[str, Field(max_length=250)] = "",
                        sort: Literal["agent", "repos", "stars"] = "agent", include_facet_counts: bool = False,
                        limit: Limit = 10, offset: Offset = 0) -> dict[str, Any]:
        """Find people by GitHub username, exact owner/repo or intersecting work facets. sort: agent (most agent-related work, default), repos, stars. Rows retain agent_work_count; stars count matching owned repos. Pass github_id to get_developer."""
        data = catalog.developers(dict(q=q, topic=topic, target=target, contribution=contribution, repository=repository,
                                      sort=sort, include_facet_counts=include_facet_counts, limit=limit, offset=offset))
        return {**data, "total": data.get("count", data.get("total", 0))}

    @server.tool(annotations=annotations)
    def get_developer(github_id: Annotated[int, Field(gt=0, le=9223372036854775807)],
                      limit: Limit = 10, offset: Offset = 0) -> dict[str, Any]:
        """Get a person's ownership and GitHub-reported commit evidence with paged repositories. Contributions do not establish paper authorship."""
        data = catalog.developer(github_id)
        repos = data.get("repositories", [])
        return {**data, "total": len(repos), "repositories_total": len(repos),
                "repositories": repos[offset:offset + limit], "limit": limit, "offset": offset}

    for name in ("list_organizations", "list_conferences", "list_frameworks"):
        server.remove_tool(name)

    @server.tool(annotations=annotations)
    def list_organizations(featured_only: bool = False, sort: Literal["trending", "papers", "stars", "name"] | None = None,
                           limit: Limit = 10, offset: Offset = 0) -> dict[str, Any]:
        """List publishers/organizations with catalog counts and catalog_url. sort: trending, papers (papers+agent posts), stars, name; omitted preserves catalog order. Counts are across all topics. Use get_organization for details."""
        return {"schema_version": "v1", "data": page(run("list_organizations", featured_only=featured_only, sort=sort), limit, offset)}

    @server.tool(annotations=annotations)
    def list_conferences(year: int | None = None, limit: Limit = 10, offset: Offset = 0) -> dict[str, Any]:
        """List conferences with imported papers, optionally by numeric year."""
        return {"schema_version": "v1", "data": page(run("list_conferences", year=year), limit, offset)}

    @server.tool(annotations=annotations)
    def list_frameworks(domain: str | None = None, category: str | None = None, platform: str | None = None,
                        limit: Limit = 10, offset: Offset = 0) -> dict[str, Any]:
        """List frameworks by exact domain/category name or slug and platform name from returned rows; omit unknown filters. Sparse in this security catalog."""
        return {"schema_version": "v1", "data": page(run("list_frameworks", domain=domain, category=category, platform=platform), limit, offset)}
