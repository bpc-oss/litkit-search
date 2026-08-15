"""Tests for scite.ai source (mocked HTTP via respx)."""

import pytest
import respx

from litkit.config import EnvConfig
from litkit.sources.scite import SciteSource


@pytest.fixture
def config():
    return EnvConfig(scite_key="test-key-123")


_SAMPLE_PAPER = {
    "title": "Test Paper Title",
    "year": 2023,
    "journal": "Test Journal",
    "authors": ["Doe, John", "Smith J"],
    "doi": "10.1234/test",
    "url": "https://doi.org/10.1234/test",
    "cited_by": 42,
    "reference_count": 25,
    "citation_statements": [
        {
            "citing_title": "A Citing Paper",
            "text": "This paper demonstrates a significant improvement.",
        }
    ],
}


_SAMPLE_PAPER_NO_CONTEXTS = {
    "title": "Another Paper",
    "year": 2022,
    "journal": "Another Journal",
    "authors": ["Brown, Alice"],
    "doi": "10.1234/another",
    "url": "https://doi.org/10.1234/another",
    "cited_by": 5,
    "reference_count": 10,
    "citation_statements": [],
}


@pytest.mark.asyncio
@respx.mock
async def test_fetch_by_doi(config):
    route = respx.get("https://api.scite.ai/api/v1/papers", params={"doi": "10.1234/test"}).respond(
        200,
        json=[_SAMPLE_PAPER],
        headers={"Authorization": "Bearer test-key-123"},
    )
    src = SciteSource(config)
    p = await src.fetch_by_doi("10.1234/test")
    assert route.called
    assert p is not None
    assert p.doi == "10.1234/test"
    assert p.title == "Test Paper Title"
    assert p.year == 2023
    assert p.venue.name == "Test Journal"
    assert p.citations_count == 42
    assert p.references_count == 25
    assert len(p.authors) == 2
    assert p.authors[0].family == "Doe"
    assert p.authors[0].given == "John"
    assert p.authors[1].family == "J"
    assert p.authors[1].given == "Smith"
    assert "scite_contexts" in p.extra
    assert len(p.extra["scite_contexts"]) == 1
    assert p.extra["scite_contexts"][0]["citing_title"] == "A Citing Paper"
    assert (
        p.extra["scite_contexts"][0]["text"] == "This paper demonstrates a significant improvement."
    )


@pytest.mark.asyncio
@respx.mock
async def test_fetch_by_doi_not_found(config):
    route = respx.get(
        "https://api.scite.ai/api/v1/papers", params={"doi": "10.1234/missing"}
    ).respond(
        404,
        json={"error": "not found"},
        headers={"Authorization": "Bearer test-key-123"},
    )
    src = SciteSource(config)
    p = await src.fetch_by_doi("10.1234/missing")
    assert route.called
    assert p is None


@pytest.mark.asyncio
@respx.mock
async def test_search_returns_empty(config):
    src = SciteSource(config)
    result = await src.search("test query", limit=10)
    assert len(result.papers) == 0
    assert result.total_estimated == 0
    assert result.source == "scite"
