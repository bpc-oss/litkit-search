"""Tests for Crossref source (mocked HTTP via respx)."""

import pytest
import respx

from litkit.config import EnvConfig
from litkit.sources.crossref import Crossref


@pytest.fixture
def config():
    return EnvConfig(crossref_email="test@example.com")


_SAMPLE_ITEM = {
    "DOI": "10.1234/test",
    "title": ["Test Paper Title"],
    "author": [{"given": "John", "family": "Doe"}],
    "container-title": ["Test Journal"],
    "ISSN": ["1234-5678"],
    "publisher": "Test Publisher",
    "type": "journal-article",
    "volume": "10",
    "issue": "2",
    "page": "100-110",
    "published-print": {"date-parts": [[2023, 5, 1]]},
    "abstract": "<jats:p>Test abstract.</jats:p>",
    "subject": ["Computer Science", "Machine Learning"],
    "license": [{"URL": "https://creativecommons.org/licenses/by/4.0/"}],
}


@pytest.mark.asyncio
@respx.mock
async def test_search(config):
    route = respx.get("https://api.crossref.org/works").respond(
        200, json={"message": {"total-results": 1, "items": [_SAMPLE_ITEM]}}
    )
    src = Crossref(config)
    result = await src.search("test query", limit=10)
    assert route.called
    assert len(result.papers) == 1
    p = result.papers[0]
    assert p.doi == "10.1234/test"
    assert p.title == "Test Paper Title"
    assert p.year == 2023
    assert p.authors[0].family == "Doe"
    assert p.venue.name == "Test Journal"
    assert p.venue.issn == "1234-5678"
    assert p.venue.publisher == "Test Publisher"
    assert p.volume == "10"
    assert p.issue == "2"
    assert p.pages == "100-110"


@pytest.mark.asyncio
@respx.mock
async def test_search_empty(config):
    respx.get("https://api.crossref.org/works").respond(
        200, json={"message": {"total-results": 0, "items": []}}
    )
    src = Crossref(config)
    result = await src.search("nothing")
    assert len(result.papers) == 0


@pytest.mark.asyncio
@respx.mock
async def test_fetch_by_doi(config):
    respx.get("https://api.crossref.org/works/10.1234/test").respond(
        200, json={"message": _SAMPLE_ITEM}
    )
    src = Crossref(config)
    p = await src.fetch_by_doi("10.1234/test")
    assert p is not None
    assert p.doi == "10.1234/test"
    assert p.title == "Test Paper Title"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_by_doi_not_found(config):
    respx.get("https://api.crossref.org/works/10.1234/missing").respond(404)
    src = Crossref(config)
    assert await src.fetch_by_doi("10.1234/missing") is None
