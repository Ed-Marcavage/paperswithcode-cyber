from types import SimpleNamespace

import pytest

from backend.utils import urls


@pytest.mark.parametrize(
    ("discovery", "version", "suffix"),
    [(True, "v1", "v1"), (True, None, ""), (True, "v2", "v2"),
     (False, "v1", ""), (False, None, ""), (False, "v2", "v2")],
)
def test_reviewed_revision_links(monkeypatch, discovery, version, suffix):
    settings = SimpleNamespace(discovery_catalog=discovery, arxiv_base_url="https://arxiv.org")
    monkeypatch.setattr(urls, "get_settings", lambda: settings)
    paper = "2512.14233"
    assert urls.get_arxiv_abs_url(paper, version) == f"https://arxiv.org/abs/{paper}{suffix}"
    assert urls.get_arxiv_pdf_url(paper, version) == f"https://arxiv.org/pdf/{paper}{suffix}.pdf"


@pytest.mark.parametrize("discovery", [False, True])
def test_publisher_pdf_is_explicit_and_catalog_scoped(monkeypatch, discovery):
    monkeypatch.setattr(urls, "get_settings", lambda: SimpleNamespace(discovery_catalog=discovery))
    pdf = "https://aclanthology.org/2025.acl-long.562.pdf"
    assert urls.get_paper_pdf_url("external", None, None) is None
    assert urls.get_paper_pdf_url("external", None, None, pdf) == (pdf if discovery else None)
