"""Tests for Zenodo source."""

import pytest
import respx

from litkit.config import EnvConfig
from litkit.sources import get
from litkit.sources.zenodo import Zenodo


@pytest.fixture
def config():
    return EnvConfig()


_SAMPLE_RECORD = {
    "id": 12345,
    "doi": "10.5281/zenodo.12345",
    "links": {"html": "https://zenodo.org/records/12345"},
    "metadata": {
        "title": "A Zenodo Dataset",
        "doi": "10.5281/zenodo.12345",
        "creators": [{"name": "Doe, Jane"}, {"name": "Smith Lab"}],
        "publication_date": "2024-02-03",
        "description": "<p>Dataset description.</p>",
        "keywords": ["dataset", "test"],
        "access_right": "open",
        "license": {"id": "cc-by-4.0"},
        "resource_type": {"type": "dataset", "title": "Dataset"},
    },
    "files": [
        {
            "key": "data.csv",
            "links": {"self": "https://zenodo.org/api/records/12345/files/data.csv/content"},
        },
        {
            "key": "paper.pdf",
            "links": {"self": "https://zenodo.org/api/records/12345/files/paper.pdf/content"},
        },
    ],
}


@pytest.mark.asyncio
@respx.mock
async def test_search(config):
    route = respx.get("https://zenodo.org/api/records").respond(
        200,
        json={"hits": {"total": 1, "hits": [_SAMPLE_RECORD]}},
    )
    src = Zenodo(config)
    result = await src.search("dataset", limit=5)
    assert route.called
    assert result.source == "zenodo"
    assert result.total_estimated == 1
    paper = result.papers[0]
    assert paper.doi == "10.5281/zenodo.12345"
    assert paper.title == "A Zenodo Dataset"
    assert paper.year == 2024
    assert paper.venue.name == "Zenodo"
    assert paper.pdf_url.endswith("paper.pdf/content")
    assert paper.subjects == ("dataset", "test")
    assert paper.authors[0].family == "Doe"
    assert paper.authors[0].given == "Jane"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_by_doi(config):
    respx.get("https://zenodo.org/api/records").respond(
        200,
        json={"hits": {"total": 1, "hits": [_SAMPLE_RECORD]}},
    )
    src = Zenodo(config)
    paper = await src.fetch_by_doi("10.5281/zenodo.12345")
    assert paper is not None
    assert paper.doi == "10.5281/zenodo.12345"


def test_zenodo_registered():
    assert get("zenodo") is Zenodo


def test_parse_uses_self_html_and_string_record_id(config):
    record = dict(_SAMPLE_RECORD)
    record["links"] = {"self_html": "https://zenodo.org/records/12345"}
    paper = Zenodo(config)._parse(record)
    assert paper.source_url == "https://zenodo.org/records/12345"

    record["links"] = {}
    paper = Zenodo(config)._parse(record)
    assert paper.source_url == "https://zenodo.org/records/12345"
