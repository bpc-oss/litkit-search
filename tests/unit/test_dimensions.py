"""Tests for Dimensions source (mocked HTTP via respx)."""

import pytest
import respx

from litkit.config import EnvConfig
from litkit.sources.dimensions import Dimensions


@pytest.fixture
def config():
    return EnvConfig()


_SAMPLE_PUBLICATION = {
    "doi": "10.1234/test",
    "title": "Test Dimensions Paper",
    "authors": [{"first_name": "John", "last_name": "Doe", "orcid": "0000-0001-2345-6789"}],
    "journal": {"title": "Test Journal"},
    "publisher": "Test Publisher",
    "abstract": "This is a test abstract.",
    "year": 2023,
    "volume": "10",
    "issue": "2",
    "pages": "100-110",
    "type": "article",
    "open_access": True,
    "field_hdr": ["Computer Science", "Machine Learning"],
    "altmetrics": {"citations_count": 42},
    "reference_ids": ["ref1", "ref2"],
}


@pytest.mark.asyncio
@respx.mock
async def test_search(config):
    route = respx.post("https://api.dimensions.ai/api/dsl").respond(
        200,
        json={"results": [{"publications": [_SAMPLE_PUBLICATION]}]},
    )
    src = Dimensions(config)
    src._api_key = "test-dimensions-key"
    result = await src.search("test query", limit=10)
    assert route.called
    assert len(result.papers) == 1
    p = result.papers[0]
    assert p.doi == "10.1234/test"
    assert p.title == "Test Dimensions Paper"
    assert p.year == 2023
    assert p.authors[0].family == "Doe"
    assert p.authors[0].given == "John"
    assert p.authors[0].orcid == "0000-0001-2345-6789"
    assert p.venue.name == "Test Journal"
    assert p.venue.publisher == "Test Publisher"
    assert p.volume == "10"
    assert p.issue == "2"
    assert p.pages == "100-110"
    assert p.citations_count == 42
    assert p.references_count == 2
    assert p.oa_status == "gold"
    assert "Computer Science" in p.subjects
    assert "Machine Learning" in p.subjects
    assert p.abstract == "This is a test abstract."
    assert p.source_url == "https://doi.org/10.1234/test"


@pytest.mark.asyncio
@respx.mock
async def test_search_empty(config):
    respx.post("https://api.dimensions.ai/api/dsl").respond(
        200,
        json={"results": [{"publications": []}]},
    )
    src = Dimensions(config)
    src._api_key = "test-dimensions-key"
    result = await src.search("nothing")
    assert len(result.papers) == 0


@pytest.mark.asyncio
@respx.mock
async def test_fetch_by_doi(config):
    route = respx.post("https://api.dimensions.ai/api/dsl").respond(
        200,
        json={"results": [{"publications": [_SAMPLE_PUBLICATION]}]},
    )
    src = Dimensions(config)
    src._api_key = "test-dimensions-key"
    p = await src.fetch_by_doi("10.1234/test")
    assert route.called
    assert p is not None
    assert p.doi == "10.1234/test"
    assert p.title == "Test Dimensions Paper"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_by_doi_not_found(config):
    respx.post("https://api.dimensions.ai/api/dsl").respond(
        200,
        json={"results": [{"publications": []}]},
    )
    src = Dimensions(config)
    src._api_key = "test-dimensions-key"
    p = await src.fetch_by_doi("10.1234/missing")
    assert p is None
