"""Tests for the bioRxiv/medRxiv downloader."""

from pathlib import Path

import pytest
import respx

from litkit.config import EnvConfig
from litkit.core.cache import MetadataCache
from litkit.core.models import Paper
from litkit.downloaders.biorxiv import BiorxivDownloader


@pytest.fixture
def cache(tmp_path: Path):
    db_path = tmp_path / "test.db"
    return MetadataCache(db_path)


@pytest.mark.asyncio
async def test_biorxiv_can_handle_biorxiv(cache):
    dl = BiorxivDownloader(cache, EnvConfig())
    paper = Paper(doi="10.1234/biorxiv-test", title="Test", extra={"server": "biorxiv"})
    assert await dl.can_handle(paper)
    await dl.close()


@pytest.mark.asyncio
async def test_biorxiv_can_handle_medrxiv(cache):
    dl = BiorxivDownloader(cache, EnvConfig())
    paper = Paper(doi="10.1234/medrxiv-test", title="Test", extra={"server": "medrxiv"})
    assert await dl.can_handle(paper)
    await dl.close()


@pytest.mark.asyncio
async def test_biorxiv_can_handle_other_server(cache):
    dl = BiorxivDownloader(cache, EnvConfig())
    paper = Paper(doi="10.1234/other-test", title="Test", extra={"server": "crossref"})
    assert not await dl.can_handle(paper)
    await dl.close()


@pytest.mark.asyncio
async def test_biorxiv_can_handle_no_doi(cache):
    dl = BiorxivDownloader(cache, EnvConfig())
    paper = Paper(title="No DOI", extra={"server": "biorxiv"})
    assert not await dl.can_handle(paper)
    await dl.close()


@pytest.mark.asyncio
@respx.mock
async def test_biorxiv_download_success(cache):
    doi = "10.1234/biorxiv-success"
    url = f"https://www.biorxiv.org/content/{doi}.full.pdf"

    respx.get(url).respond(
        200,
        headers={"content-type": "application/pdf"},
        content=b"%PDF-test-content",
    )

    dl = BiorxivDownloader(cache, EnvConfig())
    paper = Paper(doi=doi, title="bioRxiv Success", extra={"server": "biorxiv"})
    result = await dl.download(paper)
    assert result is not None
    assert result.exists()
    assert result.name.endswith(".pdf")
    await dl.close()


@pytest.mark.asyncio
@respx.mock
async def test_biorxiv_download_404(cache):
    doi = "10.1234/biorxiv-404"
    url = f"https://www.biorxiv.org/content/{doi}.full.pdf"

    respx.get(url).respond(404)

    dl = BiorxivDownloader(cache, EnvConfig())
    paper = Paper(doi=doi, title="bioRxiv 404", extra={"server": "biorxiv"})
    result = await dl.download(paper)
    assert result is None
    await dl.close()


@pytest.mark.asyncio
@respx.mock
async def test_biorxiv_download_not_pdf(cache):
    doi = "10.1234/biorxiv-not-pdf"
    url = f"https://www.biorxiv.org/content/{doi}.full.pdf"

    respx.get(url).respond(
        200,
        headers={"content-type": "text/html"},
        content="<html>not a pdf</html>",
    )

    dl = BiorxivDownloader(cache, EnvConfig())
    paper = Paper(doi=doi, title="bioRxiv Not PDF", extra={"server": "biorxiv"})
    result = await dl.download(paper)
    assert result is None
    await dl.close()
