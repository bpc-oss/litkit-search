"""Tests for OpenAlex source (mocked HTTP via respx)."""

import pytest
import respx

from litkit.config import EnvConfig
from litkit.sources.openalex import OpenAlex


@pytest.fixture
def config():
    return EnvConfig(openalex_key="test-key", crossref_email="test@example.com")


_ONE_RESULT = {
    "id": "https://openalex.org/W123",
    "doi": "https://doi.org/10.1234/test",
    "title": "Test Paper",
    "publication_year": 2023,
    "cited_by_count": 42,
    "authorships": [{"author": {"given_name": "John", "family_name": "Doe", "orcid": "0000-0001"}}],
    "primary_location": {
        "source": {"display_name": "Test Journal", "issn_l": "1234-5678", "type": "journal"}
    },
    "open_access": {"oa_url": "https://example.com/paper.pdf", "status": "gold"},
    "concepts": [{"display_name": "Machine Learning", "score": 80}],
    "biblio": {"volume": "10", "issue": "2", "pages": "100-110"},
    "referenced_works": ["W1", "W2"],
    "abstract_inverted_index": {"Test": [0], "paper": [1]},
}


@pytest.mark.asyncio
@respx.mock
async def test_search(config):
    route = respx.get("https://api.openalex.org/works").respond(
        200, json={"meta": {"count": 1}, "results": [_ONE_RESULT]}
    )
    source = OpenAlex(config)
    result = await source.search("test query", limit=10)
    assert route.called
    assert len(result.papers) == 1
    p = result.papers[0]
    assert p.doi == "10.1234/test"
    assert p.title == "Test Paper"
    assert p.year == 2023
    assert p.citations_count == 42
    assert p.authors[0].family == "Doe"
    assert p.venue.name == "Test Journal"
    assert p.oa_status == "gold"


@pytest.mark.asyncio
@respx.mock
async def test_search_empty(config):
    respx.get("https://api.openalex.org/works").respond(
        200, json={"meta": {"count": 0}, "results": []}
    )
    source = OpenAlex(config)
    result = await source.search("nothing")
    assert len(result.papers) == 0


@pytest.mark.asyncio
@respx.mock
async def test_fetch_by_doi(config):
    respx.get("https://api.openalex.org/works/doi:10.1234/test").respond(200, json=_ONE_RESULT)
    source = OpenAlex(config)
    p = await source.fetch_by_doi("10.1234/test")
    assert p is not None
    assert p.doi == "10.1234/test"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_by_doi_not_found(config):
    respx.get("https://api.openalex.org/works/doi:10.1234/missing").respond(404)
    source = OpenAlex(config)
    assert await source.fetch_by_doi("10.1234/missing") is None
