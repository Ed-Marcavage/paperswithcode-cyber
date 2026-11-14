"""The host-to-organization file behind industry-post publishers."""
import json

import pytest

from backend.services import publishers
from backend.services.publishers import load_organizations, organization_for_url, publisher_name


def test_mapping_file_is_valid_and_flat():
    organizations = load_organizations()
    assert len(organizations) >= 40
    for organization in organizations:
        assert set(organization) <= {"name", "website_url", "hosts", "note"}
        assert organization["website_url"].startswith("https://")
        assert organization["hosts"]


@pytest.mark.parametrize(
    ("url", "organization"),
    [
        ("https://deepmind.google/discover/blog/x", "Google"),
        ("https://projectzero.google/2026/10/fuzzing-v-AI.html", "Google"),
        ("https://cloud.google.com/blog/topics/threat-intelligence/x", "Google"),
        ("https://blog.google/security/x/", "Google"),
        ("https://blog.talosintelligence.com/x/", "Cisco"),
        ("https://blogs.cisco.com/security/x", "Cisco"),
        ("https://unit42.paloaltonetworks.com/x/", "Palo Alto Networks"),
        ("https://aws.amazon.com/blogs/security/x/", "Amazon"),
        ("https://www.microsoft.com/en-us/security/blog/x", "Microsoft"),
        ("https://azure.microsoft.com/en-us/blog/x", "Microsoft"),
        ("https://securitylabs.datadoghq.com/articles/x/", "Datadog"),
        ("https://www.thezdi.com/blog/x", "Trend Micro"),
        ("https://xlab.tencent.com/en/x", "Tencent"),
        ("https://qwenlm.github.io/zh/blog/qwen3.7/", "Alibaba"),
        ("https://www.anthropic.com/research/x", "Anthropic"),
        ("https://engineering.fb.com/x", "Meta"),
    ],
)
def test_sub_brands_map_to_the_parent_company(url, organization):
    assert organization_for_url(url) == organization


def test_github_pages_and_unknown_hosts_are_not_mapped():
    assert organization_for_url("https://someone.github.io/post") is None
    assert organization_for_url("https://reverser.space/post") is None
    assert organization_for_url(None) is None


def test_publisher_name_prefers_curated_then_organization_then_map_then_host():
    url = "https://projectzero.google/2026/10/x.html"
    assert publisher_name(url, "Google Project Zero", "Google") == "Google Project Zero"
    assert publisher_name(url, None, "Alphabet") == "Alphabet"
    assert publisher_name(url) == "Google"
    assert publisher_name("https://unknown.example/post") == "unknown.example"


def test_bad_mapping_files_are_rejected(tmp_path):
    def write(organizations):
        path = tmp_path / "map.json"
        path.write_text(json.dumps({"organizations": organizations}))
        return path

    good = {"name": "A", "website_url": "https://a.example", "hosts": ["a.example"]}
    with pytest.raises(ValueError):
        load_organizations(write([good, {**good, "hosts": ["b.example"]}]))  # repeated name
    with pytest.raises(ValueError):
        load_organizations(write([good, {**good, "name": "B"}]))  # host listed twice
    with pytest.raises(ValueError):
        load_organizations(write([{**good, "hosts": ["www.a.example"]}]))
    assert publishers.host_table()["blog.google"] == "Google"
