"""Tests for Semantic Scholar source (mocked HTTP via respx)."""

import pytest
import respx

from litkit.config import EnvConfig
from litkit.sources.semantic_scholar import SemanticScholar


@pytest.fixture
def config():
    return EnvConfig()


_S2_BASE = "https://api.semanticscholar.org/graph/v1"
_S2_FIELDS = (
    "title,authors,venue,year,externalIds,abstract,"
    "citationCount,referenceCount,publicationTypes,openAccessPdf"
)

_SAMPLE_PAPER = {
    "paperId": "abc123",
    "externalIds": {"DOI": "10.1234/test-s2", "CorpusId": "12345"},
    "title": "Test S2 Paper",
    "authors": [{"name": "John Doe"}],
    "venue": "S2 Journal",
    "year": 2023,
    "abstract": "Test abstract.",
    "citationCount": 42,
    "referenceCount": 10,
    "publicationTypes": ["OpenAccess"],
    "openAccessPdf": {"url": "https://example.com/paper.pdf"},
}


@pytest.mark.asyncio
@respx.mock
async def test_search(config):
    route = respx.get("https://api.semanticscholar.org/graph/v1/paper/search").respond(
        200, json={"total": 1, "data": [_SAMPLE_PAPER]}
    )
    src = SemanticScholar(config)
    result = await src.search("test query", limit=10)
    assert route.called
    assert len(result.papers) == 1
    p = result.papers[0]
    assert p.doi == "10.1234/test-s2"
    assert p.title == "Test S2 Paper"
    assert p.year == 2023
    assert p.citations_count == 42
    assert p.authors[0].family == "Doe"
    assert p.authors[0].given == "John"
    assert p.venue.name == "S2 Journal"
    assert p.oa_status == "gold"
    assert p.pdf_url == "https://example.com/paper.pdf"


@pytest.mark.asyncio
@respx.mock
async def test_search_empty(config):
    respx.get("https://api.semanticscholar.org/graph/v1/paper/search").respond(
        200, json={"total": 0, "data": []}
    )
    src = SemanticScholar(config)
    result = await src.search("nothing")
    assert len(result.papers) == 0


@pytest.mark.asyncio
@respx.mock
async def test_search_404(config):
    respx.get("https://api.semanticscholar.org/graph/v1/paper/search").respond(404)
    src = SemanticScholar(config)
    result = await src.search("notfound")
    assert len(result.papers) == 0


@pytest.mark.asyncio
@respx.mock
async def test_fetch_by_doi(config):
    respx.get(
        f"{_S2_BASE}/paper/DOI:10.1234/test-s2",
        params={"fields": _S2_FIELDS},
    ).respond(200, json=_SAMPLE_PAPER)
    src = SemanticScholar(config)
    p = await src.fetch_by_doi("10.1234/test-s2")
    assert p is not None
    assert p.doi == "10.1234/test-s2"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_by_doi_not_found(config):
    respx.get(
        f"{_S2_BASE}/paper/DOI:10.1234/missing",
        params={"fields": _S2_FIELDS},
    ).respond(404)
    src = SemanticScholar(config)
    assert await src.fetch_by_doi("10.1234/missing") is None
