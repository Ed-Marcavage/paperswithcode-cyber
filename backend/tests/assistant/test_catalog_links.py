import copy
import json

import pytest

from backend.services.assistant_catalog_links import add_catalog_urls
from backend.tests.assistant.test_mcp import response, run


@pytest.mark.parametrize("tool", ["search_papers", "list_recent_papers", "list_trending_papers", "get_related_papers"])
def test_work_pages_cover_query_result_data_and_compact_items(tool):
    work = {"id": "134", "arxiv_id": "2602.12345v2", "title": "Paper", "source_url": "https://source.test/paper"}
    raw = {"schema_version": "v1", "data": {"results": [work]} if tool == "search_papers" else [work], "items": [work]}
    if tool == "list_trending_papers":
        raw["data"] = [{"paper_id": "88", "title": "Post", "repository": {"owner": "org", "name": "repo", "url": "https://github.com/org/repo"}}]
    original = copy.deepcopy(raw)
    result = add_catalog_urls(tool, raw)
    assert result["items"][0]["catalog_url"] == "/paper/2602.12345"
    data = result["data"]["results"] if tool == "search_papers" else result["data"]
    assert data[0]["catalog_url"] == ("/paper/88" if tool == "list_trending_papers" else "/paper/2602.12345")
    if tool == "list_trending_papers":
        assert data[0]["repository"]["catalog_url"] == "/repos/org/repo"
    assert raw == original


def test_browse_catalog_uses_reference_or_catalog_id_for_all_work_kinds():
    raw = {"results": [{"paper_id": "88", "reference": "88", "title": "Post", "source_url": "https://source.test/post"},
                       {"paper_id": "99", "reference": "cs/9901001", "title": "Legacy paper"},
                       {"paper_id": "100", "title": "Repository entry", "facets": {"kind": ["repository"]}}]}
    assert [w["catalog_url"] for w in add_catalog_urls("browse_catalog", raw)["results"]] == ["/paper/88", "/paper/99", "/paper/100"]


def test_paper_info_discovery_and_repository_resources():
    raw = {"schema_version": "v1", "in_catalog": True, "discovery": {"paper_id": "134", "reference": "2602.12345", "title": "Paper"},
           "paper": {"id": "134", "title": "Paper", "repositories": [{"url": "https://github.com/org/repo", "is_official": True},
                      {"url": "https://gitlab.com/org/repo"}, {"url": "https://github.com/org/repo/tree/main"}],
                     "tasks": [{"id": "5", "name": "Task", "slug": "task"}]}}
    result = add_catalog_urls("get_paper_info", raw)
    assert result["discovery"]["catalog_url"] == "/paper/2602.12345"
    assert result["paper"]["catalog_url"] == "/paper/134"
    assert result["paper"]["repositories"][0]["catalog_url"] == "/repos/org/repo"
    assert all("catalog_url" not in r for r in result["paper"]["repositories"][1:])
    assert "catalog_url" not in result["paper"]["tasks"][0]
    raw["in_catalog"] = False
    assert add_catalog_urls("get_paper_info", raw) == raw


@pytest.mark.parametrize("tool", ["list_organizations", "get_organization"])
def test_organizations_use_slug_not_id_and_link_nested_work(tool):
    org = {"id": "11", "slug": "meta", "name": "Meta", "top_trending_paper": {"id": "88", "title": "Post"}}
    raw = {"schema_version": "v1", "data": {"results": [org]} if tool == "list_organizations" else org}
    data = add_catalog_urls(tool, raw)["data"]
    item = data["results"][0] if tool == "list_organizations" else data
    assert item["catalog_url"] == "/orgs/meta"
    assert item["top_trending_paper"]["catalog_url"] == "/paper/88"
    assert "catalog_url" not in add_catalog_urls("get_organization", {"id": "11", "name": "Meta"})


@pytest.mark.parametrize("tool", ["list_developers", "get_developer"])
def test_developers_use_github_id_and_tracked_repositories(tool):
    dev = {"github_id": 40309309, "login": "NickNameInvalid", "repositories": [{"github_repo_id": 7, "full_name": "org/repo", "commits": 4}]}
    raw = {"count": 1, "results": [dev]} if tool == "list_developers" else dev
    result = add_catalog_urls(tool, raw)
    item = result["results"][0] if tool == "list_developers" else result
    assert item["catalog_url"] == "/developers/40309309"
    assert item["repositories"][0]["catalog_url"] == "/repos/org/repo"
    assert "catalog_url" not in add_catalog_urls(tool, {"login": "name-only", "github_id": "name-only"})
    assert "catalog_url" not in add_catalog_urls(tool, {"github_id": "1" * 19})


def test_read_paper_only_links_verified_catalog_references():
    assert add_catalog_urls("read_paper", {"paper": "134", "in_catalog": True})["catalog_url"] == "/paper/134"
    for item in [{"paper": "134", "in_catalog": False}, {"paper": "https://source.test", "in_catalog": True}, {"paper": "unknown"}]:
        assert add_catalog_urls("read_paper", item) == item


def test_filters_and_unidentified_source_only_items_have_no_guessed_page():
    filters = {"topic": {"ai-security": "AI security"}, "id": "1", "title": "Not a work"}
    assert add_catalog_urls("catalog_filters", filters) == filters
    raw = {"results": [{"title": "Source only", "source_url": "https://source.test"}, {"id": "../../admin", "title": "Bad ID"}]}
    assert add_catalog_urls("browse_catalog", raw) == raw


@pytest.mark.parametrize("structured", [True, False])
def test_adapter_adds_paths_before_capping_and_records_exact_model_size(structured):
    payload = {"results": [{"paper_id": "134", "title": "Paper"}]}
    envelope = {"structuredContent": payload} if structured else {"content": [{"type": "text", "text": json.dumps(payload)}]}
    result = run(lambda m: m.call("browse_catalog", {}), lambda r: response(r, envelope))
    assert json.loads(result.text)["results"][0]["catalog_url"] == "/paper/134"
    assert result.full_bytes == len(result.text.encode())
    envelope["isError"] = True
    failed = run(lambda m: m.call("browse_catalog", {}), lambda r: response(r, envelope))
    assert failed.is_error and "catalog_url" not in failed.text
