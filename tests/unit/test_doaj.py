"""Tests for DOAJ source (mocked HTTP via respx)."""

import pytest
import respx

from litkit.config import EnvConfig
from litkit.sources.doaj import DOAJ


@pytest.fixture
def config():
    return EnvConfig()


_BASE = "https://doaj.org/api/v3/search/articles"


@pytest.mark.asyncio
@respx.mock
async def test_search(config):
    respx.get(f"{_BASE}/test%20query").respond(
        200,
        json={
            "total": 1,
            "results": [
                {
                    "bibjson": {
                        "identifier": [{"type": "DOI", "id": "10.1234/doaj-test"}],
                        "title": "Test DOAJ Paper",
                        "journal": {
                            "title": "DOAJ Journal",
                            "volume": "10",
                            "number": "2",
                            "pages": "100-110",
                        },
                        "year": "2023",
                        "author": [{"name": "Doe, John"}],
                    }
                }
            ],
        },
    )
    src = DOAJ(config)
    result = await src.search("test query", limit=10)
    assert len(result.papers) == 1
    p = result.papers[0]
    assert p.doi == "10.1234/doaj-test"
    assert p.title == "Test DOAJ Paper"
    assert p.year == 2023


@pytest.mark.asyncio
@respx.mock
async def test_search_empty(config):
    respx.get(f"{_BASE}/nothing").respond(200, json={"total": 0, "results": []})
    src = DOAJ(config)
    result = await src.search("nothing")
    assert len(result.papers) == 0


@pytest.mark.asyncio
@respx.mock
async def test_search_500(config):
    respx.get(f"{_BASE}/error").respond(500)
    src = DOAJ(config)
    result = await src.search("error")
    assert len(result.papers) == 0


@pytest.mark.asyncio
@respx.mock
async def test_fetch_by_doi(config):
    respx.get(f"{_BASE}/doi:10.1234/doaj-found").respond(
        200,
        json={
            "total": 1,
            "results": [
                {
                    "bibjson": {
                        "identifier": [{"type": "DOI", "id": "10.1234/doaj-found"}],
                        "title": "DOAJ Found",
                        "journal": {"title": "DOAJ Journal"},
                        "year": "2023",
                    }
                }
            ],
        },
    )
    src = DOAJ(config)
    p = await src.fetch_by_doi("10.1234/doaj-found")
    assert p is not None
    assert p.title == "DOAJ Found"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_by_doi_not_found(config):
    respx.get(f"{_BASE}/doi:10.9999/missing").respond(200, json={"total": 0, "results": []})
    src = DOAJ(config)
    p = await src.fetch_by_doi("10.9999/missing")
    assert p is None
