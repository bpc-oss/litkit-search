"""Tests for bioRxiv/medRxiv source (mocked HTTP via respx)."""

import pytest
import respx

from litkit.config import EnvConfig
from litkit.sources.biorxiv import Biorxiv


@pytest.fixture
def config():
    return EnvConfig()


_SAMPLE_RESPONSE = {
    "collection": [
        {
            "doi": "10.1101/2023.01.01.123456",
            "title": "Test bioRxiv Paper",
            "date": "2023-01-15",
            "authors": "Doe, John; Smith, Jane",
            "server": "biorxiv",
        }
    ]
}

_SAMPLE_MEDRXIV_RESPONSE = {
    "collection": [
        {
            "doi": "10.1101/2023.05.01.987654",
            "title": "Test medRxiv Paper",
            "date": "2023-05-10",
            "authors": "Lee, Alice; Wang, Bob",
            "server": "medrxiv",
        }
    ]
}


@pytest.mark.asyncio
@respx.mock
async def test_fetch_by_doi(config):
    respx.get("https://api.biorxiv.org/details/biorxiv/10.1101/2023.01.01.123456").respond(
        200, json=_SAMPLE_RESPONSE
    )
    src = Biorxiv(config)
    p = await src.fetch_by_doi("10.1101/2023.01.01.123456")
    assert p is not None
    assert p.doi == "10.1101/2023.01.01.123456"
    assert p.title == "Test bioRxiv Paper"
    assert p.year == 2023
    assert p.venue.name == "bioRxiv"
    assert p.source == "biorxiv"
    assert len(p.authors) == 2
    assert p.authors[0].family == "Doe"
    assert p.authors[0].given == "John"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_by_doi_medrxiv(config):
    respx.get("https://api.biorxiv.org/details/biorxiv/10.1101/2023.05.01.987654").respond(
        200, json=_SAMPLE_MEDRXIV_RESPONSE
    )
    src = Biorxiv(config)
    p = await src.fetch_by_doi("10.1101/2023.05.01.987654")
    assert p is not None
    assert p.venue.name == "medRxiv"
    assert p.extra.get("server") == "medrxiv"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_by_doi_not_found(config):
    respx.get("https://api.biorxiv.org/details/biorxiv/10.9999/missing").respond(404)
    src = Biorxiv(config)
    p = await src.fetch_by_doi("10.9999/missing")
    assert p is None


@pytest.mark.asyncio
@respx.mock
async def test_search_uses_crossref_posted_content(config):
    route = respx.get("https://api.crossref.org/works").respond(
        200,
        json={
            "message": {
                "total-results": 1,
                "items": [
                    {
                        "DOI": "10.1101/2024.01.01.123456",
                        "title": ["Keyword matched preprint"],
                        "author": [{"given": "Jane", "family": "Doe"}],
                        "posted": {"date-parts": [[2024, 1, 1]]},
                        "institution": [{"name": "bioRxiv"}],
                        "type": "posted-content",
                        "link": [
                            {
                                "URL": "https://www.biorxiv.org/content/10.1101/2024.01.01.123456.full.pdf",
                                "content-type": "application/pdf",
                            }
                        ],
                    }
                ],
            }
        },
    )
    src = Biorxiv(config)
    result = await src.search("keyword", limit=5)
    assert route.called
    assert len(result.papers) == 1
    assert result.total_estimated == 1
    assert result.papers[0].doi == "10.1101/2024.01.01.123456"
    assert result.papers[0].title == "Keyword matched preprint"
    assert result.papers[0].venue.name == "bioRxiv"
    assert result.papers[0].extra["server"] == "biorxiv"
