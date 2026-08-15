"""Tests for BASE search source (mocked HTTP via respx)."""

import pytest
import respx

from litkit.config import EnvConfig
from litkit.sources.base_search import BASE


@pytest.fixture
def config():
    return EnvConfig()


_BASE = "https://api.base-search.net/v1"


@pytest.mark.asyncio
@respx.mock
async def test_search(config):
    respx.get(f"{_BASE}/search").respond(
        200,
        json={
            "response": {
                "numFound": 1,
                "docs": [
                    {
                        "title": ["Test BASE Paper"],
                        "author": ["Doe, John"],
                        "source": "BASE Journal",
                        "year": 2023,
                        "link": ["https://doi.org/10.1234/base-test"],
                        "dcsubject": ["Computer Science"],
                    }
                ],
            }
        },
    )
    src = BASE(config)
    result = await src.search("test query", limit=10)
    assert len(result.papers) == 1
    p = result.papers[0]
    assert p.doi == "10.1234/base-test"
    assert p.title == "Test BASE Paper"
    assert p.year == 2023
    assert p.source == "base"


@pytest.mark.asyncio
@respx.mock
async def test_search_empty(config):
    respx.get(f"{_BASE}/search").respond(200, json={"response": {"numFound": 0, "docs": []}})
    src = BASE(config)
    result = await src.search("nothing")
    assert len(result.papers) == 0


@pytest.mark.asyncio
@respx.mock
async def test_fetch_by_doi(config):
    respx.get(f"{_BASE}/search").respond(
        200,
        json={
            "response": {
                "numFound": 1,
                "docs": [
                    {
                        "title": ["BASE by DOI"],
                        "author": ["Smith, Jane"],
                        "year": 2023,
                        "link": ["https://doi.org/10.1234/base-found"],
                    }
                ],
            }
        },
    )
    src = BASE(config)
    p = await src.fetch_by_doi("10.1234/base-found")
    assert p is not None
    assert p.title == "BASE by DOI"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_by_doi_not_found(config):
    respx.get(f"{_BASE}/search").respond(200, json={"response": {"numFound": 0, "docs": []}})
    src = BASE(config)
    p = await src.fetch_by_doi("10.9999/missing")
    assert p is None
