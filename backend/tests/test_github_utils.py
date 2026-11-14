import pytest

from backend.utils.github_utils import (
    github_repository,
    normalize_github_url,
    parse_github_url,
    repository_key,
)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/wuzimeng/comp.git", ("wuzimeng", "comp")),
        ("https://github.com/AIRI-Institute/CAMAR.GIT", ("AIRI-Institute", "CAMAR")),
        ("https://github.com/owner/repo.git/", ("owner", "repo")),
        ("https://github.com/owner/name.github.io", ("owner", "name.github.io")),
        ("https://github.com/owner/.git", (None, None)),
    ],
)
def test_parse_github_url_strips_clone_suffix(url, expected):
    assert parse_github_url(url) == expected


def test_normalize_github_url_drops_clone_suffix():
    assert (
        normalize_github_url("github.com/YU-deep/MACT.git")
        == "https://github.com/yu-deep/mact"
    )


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/NVIDIA/OpenShell", ("NVIDIA", "OpenShell")),
        ("https://www.github.com/org/repo.git", ("org", "repo")),
        ("http://github.com/org/repo/tree/main/sub/dir?tab=readme#top", ("org", "repo")),
        ("https://github.com/rapid7/metasploit-framework/pull/18497", ("rapid7", "metasploit-framework")),
        ("github.com/org/repo", ("org", "repo")),
        ("https://api.github.com/repos/org/repo/contents/x", ("org", "repo")),
        ("https://raw.githubusercontent.com/org/repo/main/README.md", ("org", "repo")),
        ("https://github.com/owner/name.github.io", ("owner", "name.github.io")),
        # Not one repository:
        ("https://github.com/org", None),
        ("https://github.com/Xpos587?tab=repositories", None),
        ("https://github.com/advisories/GHSA-abcd-1234", None),
        ("https://github.com/orgs/acme/repositories", None),
        ("https://github.com/topics/security", None),
        ("https://gist.github.com/user/0123abcd", None),
        ("https://google-deepmind.github.io/code-verification", None),
        ("https://gitlab.com/group/project", None),
        ("https://github.com/owner/.git", None),
        ("https://github.com/owner/..", None),
        ("ftp://github.com/org/repo", None),
        ("", None),
        (None, None),
    ],
)
def test_github_repository_reads_one_repository_from_any_link(url, expected):
    assert github_repository(url) == expected


def test_repository_key_is_case_insensitive():
    keys = {
        repository_key(url)
        for url in (
            "https://github.com/NVIDIA/OpenShell",
            "https://github.com/nvidia/openshell.git",
            "https://github.com/Nvidia/OpenShell/blob/main/README.md",
            "https://api.github.com/repos/NVIDIA/OPENSHELL",
        )
    }
    assert keys == {"nvidia/openshell"}
