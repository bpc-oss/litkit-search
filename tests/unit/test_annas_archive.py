"""Tests for the Anna's Archive downloader."""

from pathlib import Path

import httpx
import pytest
import respx

from litkit.config import EnvConfig
from litkit.core.cache import MetadataCache
from litkit.core.models import Paper
from litkit.downloaders.annas_archive import AnnasArchiveDownloader


@pytest.fixture
def cache(tmp_path: Path) -> MetadataCache:
    db_path = tmp_path / "test.db"
    return MetadataCache(db_path)


@pytest.mark.asyncio
async def test_downloader_returns_none_without_doi(cache: MetadataCache) -> None:
    """download() should return None when the paper has no DOI."""
    dl = AnnasArchiveDownloader(cache, EnvConfig())
    paper = Paper(title="No DOI Paper")
    result = await dl.download(paper)
    assert result is None
    await dl.close()


@pytest.mark.asyncio
@respx.mock
async def test_downloader_returns_none_on_connection_error(
    cache: MetadataCache,
) -> None:
    """download() should gracefully return None on connection failure."""
    doi = "10.1234/connection-error"
    respx.get("https://annas-archive.gs/search?q=" + doi).mock(
        side_effect=httpx.ConnectError("Connection refused"),
    )
    respx.get("https://annas-archive.org/search?q=" + doi).mock(
        side_effect=httpx.ConnectError("Connection refused"),
    )
    respx.get("https://annas-archive.se/search?q=" + doi).mock(
        side_effect=httpx.ConnectError("Connection refused"),
    )

    dl = AnnasArchiveDownloader(cache, EnvConfig())
    paper = Paper(doi=doi, title="Connection Error Test")
    result = await dl.download(paper)
    assert result is None
    await dl.close()


@pytest.mark.asyncio
async def test_downloader_can_handle(cache: MetadataCache) -> None:
    """can_handle should return True for papers with DOI, False otherwise."""
    dl = AnnasArchiveDownloader(cache, EnvConfig())

    paper_with_doi = Paper(doi="10.1234/test", title="Test")
    assert await dl.can_handle(paper_with_doi) is True

    paper_without_doi = Paper(title="No DOI")
    assert await dl.can_handle(paper_without_doi) is False

    await dl.close()
