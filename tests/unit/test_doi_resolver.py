"""Tests for DOI Content Negotiation source (mocked HTTP via respx)."""

import pytest
import respx

from litkit.config import EnvConfig
from litkit.sources.doi_resolver import DoiResolver


@pytest.fixture
def config():
    return EnvConfig()


_SAMPLE_CSL = {
    "DOI": "10.1234/test",
    "title": "Test CSL Paper",
    "author": [{"given": "John", "family": "Doe"}],
    "container-title": "Test Journal",
    "publisher": "Test Publisher",
    "type": "journal-article",
    "volume": "10",
    "issue": "2",
    "page": "100-110",
    "issued": {"date-parts": [[2023, 5, 1]]},
    "abstract": "This is a test abstract.",
    "keyword": "Machine Learning, AI",
}


@pytest.mark.asyncio
@respx.mock
async def test_fetch_by_doi(config):
    route = respx.get("https://doi.org/10.1234/test").respond(
        200,
        json=_SAMPLE_CSL,
    )
    src = DoiResolver(config)
    p = await src.fetch_by_doi("10.1234/test")
    assert route.called
    assert p is not None
    assert p.doi == "10.1234/test"
    assert p.title == "Test CSL Paper"
    assert p.year == 2023
    assert p.authors[0].family == "Doe"
    assert p.authors[0].given == "John"
    assert p.venue.name == "Test Journal"
    assert p.venue.publisher == "Test Publisher"
    assert p.venue.type == "journal-article"
    assert p.volume == "10"
    assert p.issue == "2"
    assert p.pages == "100-110"
    assert "Machine Learning" in p.keywords
    assert "AI" in p.keywords
    assert p.abstract == "This is a test abstract."
    assert p.source_url == "https://doi.org/10.1234/test"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_by_doi_not_found(config):
    route = respx.get("https://doi.org/10.1234/missing").respond(404)
    src = DoiResolver(config)
    p = await src.fetch_by_doi("10.1234/missing")
    assert route.called
    assert p is None


@pytest.mark.asyncio
@respx.mock
async def test_search_returns_empty(config):
    src = DoiResolver(config)
    result = await src.search("anything")
    assert len(result.papers) == 0
    assert result.source == "doi_resolver"
