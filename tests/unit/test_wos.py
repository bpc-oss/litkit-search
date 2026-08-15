"""Tests for Web of Science source (mocked HTTP via respx)."""

import pytest
import respx

from litkit.config import EnvConfig
from litkit.sources.wos import Wos


@pytest.fixture
def config():
    return EnvConfig(wos_key="test-wos-key")


_SAMPLE_HIT = {
    "title": "Test WoS Paper",
    "names": {
        "authors": [{"displayName": "Doe, John"}],
    },
    "source": {
        "sourceTitle": "WoS Journal",
        "publishYear": "2023",
        "volume": "10",
        "issue": "2",
        "pages": {"range": "100-110"},
    },
    "identifiers": {
        "doi": "10.1234/test-wos",
        "issn": "1234-5678",
    },
    "citations": [{"count": 42}],
}


@pytest.mark.asyncio
@respx.mock
async def test_search(config):
    route = respx.get("https://api.clarivate.com/apis/wos-starter/v1/documents").respond(
        200,
        json={
            "hits": [_SAMPLE_HIT],
            "metadata": {"total": 1},
        },
    )
    src = Wos(config)
    result = await src.search("test query", limit=10)
    assert route.called
    assert len(result.papers) == 1
    p = result.papers[0]
    assert p.doi == "10.1234/test-wos"
    assert p.title == "Test WoS Paper"
    assert p.year == 2023
    assert p.citations_count == 42
    assert p.authors[0].family == "Doe"
    assert p.authors[0].given == "John"
    assert p.venue.name == "WoS Journal"
    assert p.volume == "10"
    assert p.issue == "2"


@pytest.mark.asyncio
@respx.mock
async def test_search_no_key(config):
    src = Wos(EnvConfig())
    result = await src.search("test")
    assert len(result.papers) == 0


@pytest.mark.asyncio
@respx.mock
async def test_search_403(config):
    respx.get("https://api.clarivate.com/apis/wos-starter/v1/documents").respond(403)
    src = Wos(config)
    result = await src.search("test")
    assert len(result.papers) == 0


@pytest.mark.asyncio
@respx.mock
async def test_fetch_by_doi(config):
    respx.get("https://api.clarivate.com/apis/wos-starter/v1/documents").respond(
        200,
        json={
            "hits": [_SAMPLE_HIT],
            "metadata": {"total": 1},
        },
    )
    src = Wos(config)
    p = await src.fetch_by_doi("10.1234/test-wos")
    assert p is not None
    assert p.doi == "10.1234/test-wos"
