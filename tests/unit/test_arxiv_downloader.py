"""Tests for the arXiv downloader."""

from pathlib import Path

import pytest
import respx

from litkit.config import EnvConfig
from litkit.core.cache import MetadataCache
from litkit.core.models import Paper
from litkit.downloaders.arxiv import ArxivDownloader


@pytest.fixture
def cache(tmp_path: Path):
    db_path = tmp_path / "test.db"
    return MetadataCache(db_path)


@pytest.mark.asyncio
@respx.mock
async def test_arxiv_downloader_download(cache):
    respx.get("https://arxiv.org/pdf/2101.00001.pdf").respond(
        200,
        headers={"content-type": "application/pdf"},
        content=b"%PDF-test-content",
    )
    dl = ArxivDownloader(cache, EnvConfig())
    paper = Paper(
        doi="10.1234/arxiv-test",
        title="Test",
        source="arxiv",
        pdf_url="https://arxiv.org/pdf/2101.00001.pdf",
    )
    result = await dl.download(paper)
    assert result is not None
    assert result.exists()
    await dl.close()


@pytest.mark.asyncio
@respx.mock
async def test_arxiv_downloader_not_pdf(cache):
    respx.get("https://arxiv.org/pdf/2101.00002.pdf").respond(
        200,
        headers={"content-type": "text/html"},
        content="not a pdf",
    )
    dl = ArxivDownloader(cache, EnvConfig())
    paper = Paper(
        doi="10.1234/not-pdf",
        title="Test",
        source="arxiv",
        pdf_url="https://arxiv.org/pdf/2101.00002.pdf",
    )
    result = await dl.download(paper)
    assert result is None
    await dl.close()


@pytest.mark.asyncio
@respx.mock
async def test_arxiv_downloader_404(cache):
    respx.get("https://arxiv.org/pdf/2101.09999.pdf").respond(404)
    dl = ArxivDownloader(cache, EnvConfig())
    paper = Paper(
        doi="10.1234/missing",
        title="Test",
        source="arxiv",
        pdf_url="https://arxiv.org/pdf/2101.09999.pdf",
    )
    result = await dl.download(paper)
    assert result is None
    await dl.close()


@pytest.mark.asyncio
async def test_arxiv_can_handle_arxiv_source(cache):
    dl = ArxivDownloader(cache, EnvConfig())
    paper = Paper(doi="10.1234/test", title="Test", source="arxiv")
    assert await dl.can_handle(paper)
    await dl.close()


@pytest.mark.asyncio
async def test_arxiv_can_handle_other_source(cache):
    dl = ArxivDownloader(cache, EnvConfig())
    paper = Paper(doi="10.1234/test", title="Test", source="crossref")
    assert not await dl.can_handle(paper)
    await dl.close()
