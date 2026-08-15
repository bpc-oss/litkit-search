"""Tests for ChemRxiv source (mocked HTTP via respx)."""

import pytest
import respx

from litkit.config import EnvConfig
from litkit.sources.chemrxiv import Chemrxiv


@pytest.fixture
def config():
    return EnvConfig()


_SAMPLE_RESPONSE = {
    "doi": "10.26434/chemrxiv-2023-abc12",
    "title": "Test ChemRxiv Paper",
    "authors": [
        {"firstName": "John", "lastName": "Doe"},
        {"firstName": "Jane", "lastName": "Smith"},
    ],
    "publishedDate": "2023-06-01T12:00:00Z",
    "abstract": "A test abstract for chemrxiv.",
}


@pytest.mark.asyncio
@respx.mock
async def test_fetch_by_doi(config):
    respx.get(
        "https://chemrxiv.org/engage/chemrxiv/public-api/v1/item/doi/10.26434/chemrxiv-2023-abc12"
    ).respond(200, json=_SAMPLE_RESPONSE)
    src = Chemrxiv(config)
    p = await src.fetch_by_doi("10.26434/chemrxiv-2023-abc12")
    assert p is not None
    assert p.doi == "10.26434/chemrxiv-2023-abc12"
    assert p.title == "Test ChemRxiv Paper"
    assert p.year == 2023
    assert p.venue.name == "ChemRxiv"
    assert p.source == "chemrxiv"
    assert p.oa_status == "green"
    assert p.abstract == "A test abstract for chemrxiv."
    assert len(p.authors) == 2
    assert p.authors[0].given == "John"
    assert p.authors[0].family == "Doe"
    assert p.authors[1].given == "Jane"
    assert p.authors[1].family == "Smith"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_by_doi_not_found(config):
    respx.get(
        "https://chemrxiv.org/engage/chemrxiv/public-api/v1/item/doi/10.9999/missing"
    ).respond(404)
    src = Chemrxiv(config)
    p = await src.fetch_by_doi("10.9999/missing")
    assert p is None


@pytest.mark.asyncio
@respx.mock
async def test_search_returns_empty(config):
    src = Chemrxiv(config)
    result = await src.search("anything")
    assert len(result.papers) == 0
    assert result.total_estimated == 0
