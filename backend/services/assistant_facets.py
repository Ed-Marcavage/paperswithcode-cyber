"""Normalize model facet arguments and explain empty or invalid searches."""

import json

FACETS = ("topic", "target", "contribution", "kind", "year")
FACET_TOOLS = {"browse_catalog", "list_developers"}


def normalize_facets(name, arguments):
    result = dict(arguments)
    if name not in FACET_TOOLS:
        return result
    for facet in FACETS:
        value = result.get(facet)
        if isinstance(value, str):
            value = value.strip()
            if value.startswith("["):
                try:
                    value = json.loads(value)
                except ValueError:
                    pass  # Validation returns the available choices.
        if isinstance(value, list) and len(value) == 1:
            value = value[0]
        if value is None or value == []:
            value = ""
        if facet in result:
            result[facet] = value.strip() if isinstance(value, str) else value
    return result


def vocabulary(payload):
    base = payload.get("data", payload) if isinstance(payload, dict) else {}
    if not isinstance(base, dict):
        return {}
    return {axis: sorted(values) for axis, values in base.items()
            if axis in FACETS and isinstance(values, dict)
            and all(isinstance(slug, str) for slug in values)}


def invalid_facet(arguments, choices):
    for facet in FACETS:
        value = arguments.get(facet, "")
        if value == "":
            continue
        valid = choices.get(facet, [])
        if not isinstance(value, str) or value not in valid:
            return {"error": f"{facet} accepts one valid slug, not several values or a JSON array. Choose one value or omit this filter.",
                    "facet": facet, "valid_values": valid or []}
    return None


def describe_facets(tool, choices):
    if tool["function"]["name"] not in FACET_TOOLS:
        return tool
    tool["function"]["description"] += " Facets accept one slug each (not arrays). " + " ".join(
        f"{axis}: {', '.join(choices[axis])}." for axis in FACETS[:4] if axis in choices)
    return tool


def explain_empty(name, payload, arguments):
    if name not in {"browse_catalog", "search_papers"} or not isinstance(payload, dict):
        return payload
    if payload.get("total") != 0 and payload.get("results") != []:
        return payload
    if arguments.get("offset"):
        hint = "Reset offset to 0 before loosening filters; this page may be past the matches."
    elif name == "search_papers":
        hint = "This searches titles. Shorten the query or browse one topic without extra filters."
    else:
        facet = next((key for key in ("contribution", "target", "year", "topic", "kind") if arguments.get(key)), None)
        hint = f"Remove the {facet} filter first, keeping other filters unchanged." if facet else "Try a title search with a short query."
    return {**payload, "message": "Zero items returned for this request; this does not establish that the catalog lacks coverage.",
            "hint": hint}
