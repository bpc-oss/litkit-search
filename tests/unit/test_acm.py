"""Tests for ACM DL source (mocked HTTP via respx)."""

import pytest
import respx

from litkit.config import EnvConfig
from litkit.sources.acm import ACM


@pytest.fixture
def config():
    return EnvConfig(acm_key="test-acm-key")


_BASE = "https://api.acm.org/api/v1"

_SAMPLE_ITEM = {
    "doi": "10.1145/1234567",
    "title": "Test ACM Paper Title",
    "authors": [
        {"given": "John", "family": "Doe"},
        {"given": "Jane", "family": "Smith"},
    ],
    "publication_title": "ACM Test Journal",
    "publisher": "ACM",
    "abstract": "This is a test abstract for the ACM paper.",
    "year": 2023,
    "volume": "42",
    "issue": "3",
    "pages": "100-110",
}


@pytest.mark.asyncio
@respx.mock
async def test_search(config):
    route = respx.get(f"{_BASE}/search/citations").respond(
        200,
        json={
            "data": {
                "results": [_SAMPLE_ITEM],
            }
        },
    )
    src = ACM(config)
    result = await src.search("test query", limit=10)
    assert route.called
    assert len(result.papers) == 1
    p = result.papers[0]
    assert p.doi == "10.1145/1234567"
    assert p.title == "Test ACM Paper Title"
    assert p.year == 2023
    assert len(p.authors) == 2
    assert p.authors[0].family == "Doe"
    assert p.authors[0].given == "John"
    assert p.authors[1].family == "Smith"
    assert p.venue.name == "ACM Test Journal"
    assert p.venue.publisher == "ACM"
    assert p.volume == "42"
    assert p.issue == "3"
    assert p.pages == "100-110"
    assert p.abstract == "This is a test abstract for the ACM paper."


@pytest.mark.asyncio
@respx.mock
async def test_search_empty(config):
    route = respx.get(f"{_BASE}/search/citations").respond(
        200,
        json={"data": {"results": []}},
    )
    src = ACM(config)
    result = await src.search("nothing")
    assert route.called
    assert len(result.papers) == 0


@pytest.mark.asyncio
@respx.mock
async def test_fetch_by_doi(config):
    route = respx.get(f"{_BASE}/citations/doi/10.1145/1234567").respond(
        200,
        json={"data": _SAMPLE_ITEM},
    )
    src = ACM(config)
    p = await src.fetch_by_doi("10.1145/1234567")
    assert route.called
    assert p is not None
    assert p.doi == "10.1145/1234567"
    assert p.title == "Test ACM Paper Title"
    assert p.year == 2023


@pytest.mark.asyncio
@respx.mock
async def test_fetch_by_doi_not_found(config):
    route = respx.get(f"{_BASE}/citations/doi/10.1145/missing").respond(404)
    src = ACM(config)
    assert await src.fetch_by_doi("10.1145/missing") is None
    assert route.called
