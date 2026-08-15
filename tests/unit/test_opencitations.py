"""Tests for OpenCitations source (mocked HTTP via respx)."""

import pytest
import respx

from litkit.config import EnvConfig
from litkit.sources.opencitations import OpenCitations


@pytest.fixture
def config():
    return EnvConfig()


_BASE = "https://opencitations.net/index/coci/api/v1"


@pytest.mark.asyncio
@respx.mock
async def test_search(config):
    src = OpenCitations(config)
    result = await src.search("test query")
    assert len(result.papers) == 0


@pytest.mark.asyncio
@respx.mock
async def test_fetch_by_doi_returns_none(config):
    src = OpenCitations(config)
    p = await src.fetch_by_doi("10.1234/test")
    assert p is None


@pytest.mark.asyncio
@respx.mock
async def test_get_citations(config):
    respx.get(f"{_BASE}/citations/10.1234/test").respond(
        200,
        json=[
            {
                "citing": "10.1234/citing-a",
                "cited": "10.1234/test",
            }
        ],
    )
    src = OpenCitations(config)
    citing = await src.get_citations("10.1234/test")
    assert len(citing) == 1
    assert citing[0].citing_id == "10.1234/citing-a"


@pytest.mark.asyncio
@respx.mock
async def test_get_citations_not_found(config):
    respx.get(f"{_BASE}/citations/10.9999/missing").respond(404)
    src = OpenCitations(config)
    citing = await src.get_citations("10.9999/missing")
    assert len(citing) == 0


@pytest.mark.asyncio
@respx.mock
async def test_get_references(config):
    respx.get(f"{_BASE}/references/10.1234/test").respond(
        200,
        json=[
            {
                "citing": "10.1234/test",
                "cited": "10.1234/ref-a",
            }
        ],
    )
    src = OpenCitations(config)
    refs = await src.get_references("10.1234/test")
    assert len(refs) == 1
    assert refs[0].cited_id == "10.1234/ref-a"


@pytest.mark.asyncio
@respx.mock
async def test_get_references_not_found(config):
    respx.get(f"{_BASE}/references/10.9999/missing").respond(404)
    src = OpenCitations(config)
    refs = await src.get_references("10.9999/missing")
    assert len(refs) == 0
