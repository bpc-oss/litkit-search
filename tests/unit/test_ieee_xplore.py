"""Tests for IEEE Xplore source (mocked HTTP via respx)."""

import pytest
import respx

from litkit.config import EnvConfig
from litkit.sources.ieee_xplore import IeeeXplore


@pytest.fixture
def config():
    return EnvConfig()


_SAMPLE_ARTICLE = {
    "doi": "10.1109/test.2023.1234567",
    "title": "A Test IEEE Paper",
    "authors": [
        {"first_name": "John", "last_name": "Doe"},
        {"first_name": "Jane", "last_name": "Smith"},
    ],
    "publication_title": "IEEE Transactions on Testing",
    "publisher": "IEEE",
    "abstract": "This is a test abstract for an IEEE paper.",
    "publication_year": "2023",
    "volume": "42",
    "issue": "3",
    "pages": "100-110",
    "article_number": "9876543",
}


@pytest.mark.asyncio
@respx.mock
async def test_search(config):
    respx.get(
        "https://api.ieee.org/api/v1/search/articles",
        params={"querytext": "test query", "max_records": 10, "api_key": "test-key"},
    ).respond(200, json={"articles": [_SAMPLE_ARTICLE]})
    src = IeeeXplore(config)
    src._api_key = "test-key"
    result = await src.search("test query", limit=10)
    assert len(result.papers) == 1

    p = result.papers[0]
    assert p.doi == "10.1109/test.2023.1234567"
    assert p.title == "A Test IEEE Paper"
    assert p.year == 2023
    assert len(p.authors) == 2
    assert p.authors[0].family == "Doe"
    assert p.authors[0].given == "John"
    assert p.authors[1].family == "Smith"
    assert p.authors[1].given == "Jane"
    assert p.venue.name == "IEEE Transactions on Testing"
    assert p.venue.publisher == "IEEE"
    assert p.volume == "42"
    assert p.issue == "3"
    assert p.pages == "100-110"
    assert "test abstract" in p.abstract
    assert p.source == "ieee_xplore"
    assert p.extra.get("article_number") == "9876543"


@pytest.mark.asyncio
@respx.mock
async def test_search_empty(config):
    respx.get(
        "https://api.ieee.org/api/v1/search/articles",
        params={"querytext": "nothing", "max_records": 20, "api_key": "test-key"},
    ).respond(200, json={"articles": []})
    src = IeeeXplore(config)
    src._api_key = "test-key"
    result = await src.search("nothing")
    assert len(result.papers) == 0
    assert result.total_estimated == 0


@pytest.mark.asyncio
@respx.mock
async def test_fetch_by_doi(config):
    respx.get(
        "https://api.ieee.org/api/v1/search/articles",
        params={"doi": "10.1109/TEST.2023.1234567", "api_key": "test-key"},
    ).respond(200, json={"articles": [_SAMPLE_ARTICLE]})
    src = IeeeXplore(config)
    src._api_key = "test-key"
    p = await src.fetch_by_doi("10.1109/TEST.2023.1234567")
    assert p is not None
    assert p.doi == "10.1109/test.2023.1234567"
    assert p.title == "A Test IEEE Paper"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_by_doi_not_found(config):
    respx.get(
        "https://api.ieee.org/api/v1/search/articles",
        params={"doi": "10.1109/TEST.2023.missing", "api_key": "test-key"},
    ).respond(200, json={"articles": []})
    src = IeeeXplore(config)
    src._api_key = "test-key"
    assert await src.fetch_by_doi("10.1109/TEST.2023.missing") is None
