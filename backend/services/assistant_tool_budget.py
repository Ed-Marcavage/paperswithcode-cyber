"""Bound catalog requests and keep one useful, compact collection for the model."""

from copy import deepcopy

from backend.services.assistant_facets import normalize_facets

MAX_ITEMS = 10
SUMMARY_CHARS = 600
LIST_TOOLS = {"search_papers", "browse_catalog", "list_developers", "list_recent_papers",
              "list_trending_papers", "get_related_papers", "find_posts"}
COUNT_TOOLS = {"browse_catalog", "list_developers"}
SIZE_ARGUMENTS = {"limit", "page_size", "per_page", "max_results", "repo_limit"}
DESCRIPTION = " Assistant limits: at most 10 items per list; larger sizes are clamped. Results are compact projections."
COUNT_DESCRIPTION = (" include_facet_counts is ignored unless counts_only=true. Use counts_only only for counts, "
                     "not work recommendations; it returns totals/facets without item lists.")


def bounded_arguments(name, arguments):
    result = normalize_facets(name, arguments)
    for key in SIZE_ARGUMENTS & result.keys():
        value = result[key]
        if type(value) is not int:
            raise ValueError("List size must be an integer")
        result[key] = max(1, min(MAX_ITEMS, value))
    if name in LIST_TOOLS:
        result.setdefault("limit", MAX_ITEMS)
    if name in COUNT_TOOLS and result.get("counts_only") is True:
        result.update(counts_only=True, include_facet_counts=True, limit=1)
    else:
        result.pop("counts_only", None)
        result.pop("include_facet_counts", None)
    if name == "find_posts" and isinstance(result.get("topic", ""), str):
        from backend.models.assistant_tools import FindPostsArguments
        explicit_relevance = "min_agent_relevance" in result
        result = FindPostsArguments.model_validate(result).model_dump(mode="json")
        if result["query"] and not explicit_relevance:
            # This omission controls fallback behavior, including after repeated
            # normalization in the loop/adapter and in the duplicate-call cache.
            result.pop("min_agent_relevance")
    return result


def bounded_tool(tool):
    schema = deepcopy(tool["inputSchema"])
    properties = schema.setdefault("properties", {})
    for key in SIZE_ARGUMENTS & properties.keys():
        properties[key]["maximum"] = min(properties[key].get("maximum", MAX_ITEMS), MAX_ITEMS)
        if "default" in properties[key]:
            properties[key]["default"] = min(properties[key]["default"], MAX_ITEMS)
    description = tool.get("description", "") + DESCRIPTION
    if tool["name"] in COUNT_TOOLS:
        properties["counts_only"] = {"type": "boolean", "default": False,
                                     "description": "Return only totals and facet counts; no item list."}
        description += COUNT_DESCRIPTION
    return {"type": "function", "function": {"name": tool["name"], "description": description, "parameters": schema}}


ORG_FIELDS = {"id", "name", "slug", "paper_count", "post_count", "repository_count",
              "owned_repository_count", "catalog_stars", "catalog_url", "website_url"}
WORK_FIELDS = {"id", "paper_id", "arxiv_id", "reference", "title", "abstract", "published", "date_published",
               "source_url", "url_abs", "url", "catalog_url", "facets", "repository", "repositories",
               "publisher", "post_type", "tier", "agent_relevance", "tldr"}
DEV_FIELDS = {"github_id", "login", "repository_count", "featured_repo", "owned_stars", "catalog_url"}


def compact_nested(item):
    if not isinstance(item, dict):
        return item
    result = dict(item)
    for key in ("abstract", "tldr"):
        if isinstance(result.get(key), str) and len(result[key]) > SUMMARY_CHARS:
            result[key] = result[key][:SUMMARY_CHARS] + "…"
    for key in ("repositories", "papers"):
        if isinstance(result.get(key), list):
            result[key + "_total"] = len(result[key])
            result[key] = result[key][:MAX_ITEMS]
    return result


def compact_result(name, payload, arguments):
    if not isinstance(payload, (dict, list)):
        return payload
    base = payload.get("data", payload) if isinstance(payload, dict) else payload
    if isinstance(base, dict) and arguments.get("counts_only"):
        return {key: base[key] for key in ("total", "count", "facet_counts") if key in base}
    items = base if isinstance(base, list) else base.get("results") if isinstance(base, dict) else None
    if not isinstance(items, list) and isinstance(payload, dict):
        items = payload.get("items")
    if isinstance(items, list) and name in LIST_TOOLS | {"list_organizations"}:
        fields = ORG_FIELDS if name == "list_organizations" else DEV_FIELDS if name == "list_developers" else WORK_FIELDS
        shown = [compact_nested({k: v for k, v in item.items() if k in fields})
                 for item in items[:MAX_ITEMS] if isinstance(item, dict)]
        reported = base.get("total", base.get("count")) if isinstance(base, dict) else None
        result = {"total": reported if reported is not None else len(items), "returned": len(shown),
                  "total_scope": "matching_catalog" if reported is not None or name == "list_organizations" else "received_items",
                  "results": shown, "items_omitted": len(items) > len(shown)}
        if name == "list_organizations":
            result["note"] = "Counts cover each organization's catalog work, not a topic-specific publishing ranking."
        for container in (payload, base):
            if isinstance(container, dict):
                for key in ("next_page", "previous_page", "applied_filters"):
                    if key in container:
                        result[key] = container[key]
        return result
    if isinstance(payload, dict):
        result = compact_nested(payload)
        for key in ("data", "paper", "discovery"):
            if isinstance(result.get(key), dict):
                result[key] = compact_nested(result[key])
        return result
    return payload
