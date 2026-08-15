"""Tests for Springer Nature source (mocked HTTP via respx)."""

import pytest
import respx

from litkit.config import EnvConfig
from litkit.sources.springer import Springer


@pytest.fixture
def config():
    return EnvConfig(springer_key="test-springer-key")


_BASE = "https://api.springernature.com/metadata/json"

_SAMPLE_RECORD = {
    "doi": "10.1007/s00415-023-12345-6",
    "title": "Test Springer Paper Title",
    "creators": [
        {"creator": "Doe, John"},
        {"creator": "Smith, Jane"},
    ],
    "publicationName": "Springer Test Journal",
    "publisher": "Springer Nature",
    "abstract": "This is a test abstract for the Springer paper.",
    "publicationDate": "2023-06-15",
    "volume": "42",
    "number": "3",
    "startingPage": "100",
    "endingPage": "110",
    "url": "https://link.springer.com/article/10.1007/s00415-023-12345-6",
    "openaccess": "true",
    "genre": "article",
    "keyword": "machine learning, artificial intelligence, deep learning",
}


@pytest.mark.asyncio
@respx.mock
async def test_search(config):
    route = respx.get(_BASE).respond(
        200,
        json={
            "records": [_SAMPLE_RECORD],
            "result": {"total": 1},
        },
    )
    src = Springer(config)
    result = await src.search("test query", limit=10)
    assert route.called
    assert len(result.papers) == 1
    assert result.total_estimated == 1
    p = result.papers[0]
    assert p.doi == "10.1007/s00415-023-12345-6"
    assert p.title == "Test Springer Paper Title"
    assert p.year == 2023
    assert len(p.authors) == 2
    assert p.authors[0].family == "Doe"
    assert p.authors[0].given == "John"
    assert p.authors[1].family == "Smith"
    assert p.authors[1].given == "Jane"
    assert p.venue.name == "Springer Test Journal"
    assert p.venue.publisher == "Springer Nature"
    assert p.volume == "42"
    assert p.issue == "3"
    assert p.pages == "100-110"
    assert p.abstract == "This is a test abstract for the Springer paper."
    assert len(p.keywords) == 3
    assert p.keywords[0] == "machine learning"
    assert p.oa_status == "gold"


@pytest.mark.asyncio
@respx.mock
async def test_search_empty(config):
    route = respx.get(_BASE).respond(
        200,
        json={"records": [], "result": {"total": 0}},
    )
    src = Springer(config)
    result = await src.search("nothing")
    assert route.called
    assert len(result.papers) == 0
    assert result.total_estimated == 0


@pytest.mark.asyncio
@respx.mock
async def test_fetch_by_doi(config):
    route = respx.get(f"{_BASE}/doi/10.1007/s00415-023-12345-6").respond(
        200,
        json={"records": [_SAMPLE_RECORD]},
    )
    src = Springer(config)
    p = await src.fetch_by_doi("10.1007/s00415-023-12345-6")
    assert route.called
    assert p is not None
    assert p.doi == "10.1007/s00415-023-12345-6"
    assert p.title == "Test Springer Paper Title"
    assert p.year == 2023


@pytest.mark.asyncio
@respx.mock
async def test_fetch_by_doi_not_found(config):
    route = respx.get(f"{_BASE}/doi/10.1007/missing").respond(404)
    src = Springer(config)
    assert await src.fetch_by_doi("10.1007/missing") is None
    assert route.called
