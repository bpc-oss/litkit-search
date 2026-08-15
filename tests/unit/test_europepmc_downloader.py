"""Tests for the Europe PMC downloader."""

import json
from pathlib import Path

import pytest
import respx

from litkit.config import EnvConfig
from litkit.core.cache import MetadataCache
from litkit.core.models import Paper
from litkit.downloaders.europepmc import EuropePmcDownloader

_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


@pytest.fixture
def cache(tmp_path: Path):
    db_path = tmp_path / "test.db"
    return MetadataCache(db_path)


@pytest.mark.asyncio
async def test_europepmc_can_handle_with_doi(cache):
    dl = EuropePmcDownloader(cache, EnvConfig())
    paper = Paper(doi="10.1234/test", title="Test")
    assert await dl.can_handle(paper)
    await dl.close()


@pytest.mark.asyncio
async def test_europepmc_can_handle_with_pmcid(cache):
    dl = EuropePmcDownloader(cache, EnvConfig())
    paper = Paper(extra={"pmcid": "PMC123456"})
    assert await dl.can_handle(paper)
    await dl.close()


@pytest.mark.asyncio
async def test_europepmc_can_handle_without_doi_or_pmcid(cache):
    dl = EuropePmcDownloader(cache, EnvConfig())
    paper = Paper(title="No identifiers")
    assert not await dl.can_handle(paper)
    await dl.close()


@pytest.mark.asyncio
@respx.mock
async def test_europepmc_download_by_doi_success(cache):
    doi = "10.1234/pmc-doi-test"
    pdf_url = "https://example.com/pmc-paper.pdf"

    search_params = {"query": f"DOI:{doi}", "format": "json", "pageSize": "1"}
    search_response = {
        "resultList": {
            "result": [
                {
                    "pdfUrl": pdf_url,
                    "title": "Test Paper",
                }
            ]
        }
    }

    respx.get(_SEARCH_URL, params=search_params).respond(
        200,
        headers={"content-type": "application/json"},
        content=json.dumps(search_response).encode(),
    )
    respx.get(pdf_url).respond(
        200,
        headers={"content-type": "application/pdf"},
        content=b"%PDF-test-content",
    )

    dl = EuropePmcDownloader(cache, EnvConfig())
    paper = Paper(doi=doi, title="Europe PMC DOI Test")
    result = await dl.download(paper)
    assert result is not None
    assert result.exists()
    assert result.name.endswith(".pdf")
    await dl.close()


@pytest.mark.asyncio
@respx.mock
async def test_europepmc_download_by_pmcid_success(cache):
    doi = "10.1234/pmc-pmcid-test"
    pmcid = "PMC789012"
    pdf_url = f"https://europepmc.org/articles/{pmcid}/pdf"

    # Mock DOI search to return no PDF URL, forcing PMCID fallback.
    search_params = {"query": f"DOI:{doi}", "format": "json", "pageSize": "1"}
    search_response = {"resultList": {"result": [{"title": "Test"}]}}

    respx.get(_SEARCH_URL, params=search_params).respond(
        200,
        headers={"content-type": "application/json"},
        content=json.dumps(search_response).encode(),
    )
    respx.get(pdf_url).respond(
        200,
        headers={"content-type": "application/pdf"},
        content=b"%PDF-test-content",
    )

    dl = EuropePmcDownloader(cache, EnvConfig())
    paper = Paper(doi=doi, title="Europe PMC PMCID Test", extra={"pmcid": pmcid})
    result = await dl.download(paper)
    assert result is not None
    assert result.exists()
    assert result.name.endswith(".pdf")
    await dl.close()


@pytest.mark.asyncio
@respx.mock
async def test_europepmc_download_404(cache):
    doi = "10.1234/pmc-404"
    search_params = {"query": f"DOI:{doi}", "format": "json", "pageSize": "1"}

    respx.get(_SEARCH_URL, params=search_params).respond(404)

    dl = EuropePmcDownloader(cache, EnvConfig())
    paper = Paper(doi=doi, title="Europe PMC 404")
    result = await dl.download(paper)
    assert result is None
    await dl.close()


@pytest.mark.asyncio
@respx.mock
async def test_europepmc_download_not_pdf_content(cache):
    doi = "10.1234/pmc-not-pdf"
    pdf_url = "https://example.com/not-pdf"
    search_params = {"query": f"DOI:{doi}", "format": "json", "pageSize": "1"}
    search_response = {"resultList": {"result": [{"pdfUrl": pdf_url}]}}

    respx.get(_SEARCH_URL, params=search_params).respond(
        200,
        headers={"content-type": "application/json"},
        content=json.dumps(search_response).encode(),
    )
    respx.get(pdf_url).respond(
        200,
        headers={"content-type": "text/html"},
        content="<html>not a pdf</html>",
    )

    dl = EuropePmcDownloader(cache, EnvConfig())
    paper = Paper(doi=doi, title="Europe PMC Not PDF")
    result = await dl.download(paper)
    assert result is None
    await dl.close()
