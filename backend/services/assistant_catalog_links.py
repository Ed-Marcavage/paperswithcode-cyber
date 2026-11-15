"""Catalog paths for verified MCP entity shapes, never guesses from names.

Routes/lookup contracts: App.tsx; usePapers -> papersApi.get ->
PaperService.get_paper_by_id_or_arxiv; OrganizationPaperFeed -> getOrganization
(slug); Developers -> getDeveloper (numeric GitHub ID, <=18 digits); and
RepositoryReferencesView -> /catalog/repositories/{owner}/{name} (GitHub only).
Unknown schemas, taxonomy objects, source-only resources and catalog misses
are deliberately left alone. These helpers do not fetch or mutate the catalog.
"""

import re
from urllib.parse import urlsplit


def paper_path(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    value = str(value)
    if re.fullmatch(r"[1-9][0-9]*", value):
        return f"/paper/{value}"
    if match := re.fullmatch(r"([0-9]{4}\.[0-9]{4,5})(?:v[0-9]+)?", value):
        return f"/paper/{match[1]}"
    return None


def repository(item):
    if not isinstance(item, dict):
        return item
    owner, name = item.get("owner"), item.get("name")
    if not (owner and name):
        full_name = item.get("full_name")
        if not full_name and isinstance(item.get("url"), str):
            try:
                url = urlsplit(item["url"])
            except ValueError:
                return item
            if url.scheme == "https" and url.netloc == "github.com" and not url.query and not url.fragment:
                full_name = url.path.removeprefix("/")
        if isinstance(full_name, str) and full_name.count("/") == 1:
            owner, name = full_name.split("/")
    if (isinstance(owner, str) and re.fullmatch(r"[A-Za-z0-9-]+", owner)
            and isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_.-]+", name) and name not in {".", ".."}):
        return {**item, "catalog_url": f"/repos/{owner}/{name}"}
    return item


def work(item):
    if not isinstance(item, dict) or item.get("in_catalog") is False:
        return item
    result = dict(item)
    if "title" in item:
        for field in ("reference", "arxiv_id", "paper_id", "id"):
            if path := paper_path(item.get(field)):
                result["catalog_url"] = path
                break
    if "repository" in item:
        result["repository"] = repository(item["repository"])
    if isinstance(item.get("repositories"), list):
        result["repositories"] = [repository(repo) for repo in item["repositories"]]
    return result


def organization(item):
    if not isinstance(item, dict):
        return item
    result = dict(item)
    slug = item.get("slug")
    if isinstance(slug, str) and re.fullmatch(r"[A-Za-z0-9_-]+", slug):
        result["catalog_url"] = f"/orgs/{slug}"
    if isinstance(item.get("top_trending_paper"), dict):
        result["top_trending_paper"] = work(item["top_trending_paper"])
    return result


def developer(item):
    if not isinstance(item, dict):
        return item
    result = dict(item)
    github_id = str(item.get("github_id", ""))
    if re.fullmatch(r"[1-9][0-9]{0,17}", github_id):
        result["catalog_url"] = f"/developers/{github_id}"
    if isinstance(item.get("repositories"), list):
        result["repositories"] = [repository(repo) for repo in item["repositories"]]
    return result


def collection(value, decorate):
    if isinstance(value, list):
        return [decorate(item) for item in value]
    if isinstance(value, dict) and isinstance(value.get("results"), list):
        return {**value, "results": collection(value["results"], decorate)}
    return decorate(value)


def add_catalog_urls(tool, payload):
    if not isinstance(payload, dict) or payload.get("in_catalog") is False:
        return payload
    if tool == "catalog_filters":
        return payload
    if tool == "get_paper_info":
        return {key: work(value) if key in {"paper", "discovery"} else value for key, value in payload.items()}
    if tool == "read_paper":
        path = paper_path(payload.get("paper"))
        return {**payload, "catalog_url": path} if path and payload.get("in_catalog") is True else payload
    decorate = (organization if tool in {"list_organizations", "get_organization"} else
                developer if tool in {"list_developers", "get_developer"} else work)
    if "schema_version" in payload:
        return {key: collection(value, decorate) if key in {"data", "items"} else value for key, value in payload.items()}
    return collection(payload, decorate)
