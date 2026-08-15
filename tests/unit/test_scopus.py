"""Tests for Scopus source (mocked HTTP via respx)."""

import pytest
import respx

from litkit.config import EnvConfig
from litkit.sources.scopus import Scopus


@pytest.fixture
def config():
    return EnvConfig(scopus_key="test-scopus-key")


_SAMPLE_ENTRY = {
    "dc:title": "Test Scopus Paper",
    "prism:doi": "10.1234/test-scopus",
    "prism:publicationName": "Scopus Journal",
    "prism:issn": "1234-5678",
    "dc:publisher": "Elsevier",
    "prism:coverDate": "2023-06-15",
    "prism:volume": "10",
    "prism:issueIdentifier": "2",
    "prism:pageRange": "100-110",
    "citedby-count": "42",
    "subtypeDescription": "Article",
    "authkeywords": "machine learning | AI",
    "author": [{"authname": "Doe, John", "orcid": "0000-0001"}],
}


@pytest.mark.asyncio
@respx.mock
async def test_search(config):
    route = respx.get("https://api.elsevier.com/content/search/scopus").respond(
        200,
        json={
            "search-results": {
                "opensearch:totalResults": "1",
                "entry": [_SAMPLE_ENTRY],
            }
        },
    )
    src = Scopus(config)
    result = await src.search("test query", limit=10)
    assert route.called
    assert len(result.papers) == 1
    p = result.papers[0]
    assert p.doi == "10.1234/test-scopus"
    assert p.title == "Test Scopus Paper"
    assert p.year == 2023
    assert p.citations_count == 42
    assert p.authors[0].family == "Doe"
    assert p.venue.name == "Scopus Journal"
    assert p.volume == "10"
    assert p.issue == "2"


@pytest.mark.asyncio
@respx.mock
async def test_search_no_key(config):
    config_no_key = EnvConfig()
    src = Scopus(config_no_key)
    result = await src.search("test")
    assert len(result.papers) == 0


@pytest.mark.asyncio
@respx.mock
async def test_fetch_by_doi(config):
    respx.get("https://api.elsevier.com/content/search/scopus").respond(
        200,
        json={
            "search-results": {
                "opensearch:totalResults": "1",
                "entry": [_SAMPLE_ENTRY],
            }
        },
    )
    src = Scopus(config)
    p = await src.fetch_by_doi("10.1234/test-scopus")
    assert p is not None
    assert p.doi == "10.1234/test-scopus"
