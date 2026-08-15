"""Tests for the Library Genesis downloader."""

from pathlib import Path

import pytest
import respx

from litkit.config import EnvConfig
from litkit.core.cache import MetadataCache
from litkit.core.models import Paper
from litkit.downloaders.libgen import _LIBGEN_MIRRORS, LibgenDownloader

_DEFAULT_MIRROR = _LIBGEN_MIRRORS[0]

# Sample edition ID and MD5 for test responses.
_EDITION_ID = "155928091"
_MD5 = "3c42e352c0f66463e672ec04e8eb82f3"
_DOWNLOAD_KEY = "ML0C4PBP3620FEA1"


@pytest.fixture
def cache(tmp_path: Path):
    db_path = tmp_path / "test.db"
    return MetadataCache(db_path)


@pytest.mark.asyncio
async def test_libgen_can_handle_with_doi(cache):
    dl = LibgenDownloader(cache, EnvConfig())
    paper = Paper(doi="10.1234/test", title="Test")
    assert await dl.can_handle(paper)
    await dl.close()


@pytest.mark.asyncio
async def test_libgen_can_handle_without_doi(cache):
    dl = LibgenDownloader(cache, EnvConfig())
    paper = Paper(title="No DOI")
    assert not await dl.can_handle(paper)
    await dl.close()


@pytest.mark.asyncio
@respx.mock
async def test_libgen_download_success(cache):
    """Full multi-step download succeeds end-to-end."""
    doi = "10.1234/libgen-success"

    # Step 1: Search → HTML with edition ID.
    respx.get(
        f"{_DEFAULT_MIRROR}/index.php",
        params={"req": doi, "res": "25", "covers": "on", "filesuns": "all"},
    ).respond(
        200,
        headers={"content-type": "text/html"},
        content=f'<html><a href="edition.php?id={_EDITION_ID}">edition</a></html>',
    )

    # Step 2: Edition page → HTML with MD5.
    respx.get(
        f"{_DEFAULT_MIRROR}/edition.php",
        params={"id": _EDITION_ID},
    ).respond(
        200,
        headers={"content-type": "text/html"},
        content=(f'<html><a href="/ads.php?md5={_MD5}&downloadname={doi}">Libgen</a></html>'),
    )

    # Step 3: Ads page → HTML with download key.
    respx.get(
        f"{_DEFAULT_MIRROR}/ads.php",
        params={"md5": _MD5, "downloadname": doi},
    ).respond(
        200,
        headers={"content-type": "text/html"},
        content=(f'<html><a href="get.php?md5={_MD5}&key={_DOWNLOAD_KEY}"><h2>GET</h2></a></html>'),
    )

    # Step 4: get.php → 307 redirect → PDF (CDN returns octet-stream).
    respx.get(
        f"{_DEFAULT_MIRROR}/get.php",
        params={"md5": _MD5, "key": _DOWNLOAD_KEY},
    ).respond(
        200,
        headers={"content-type": "application/octet-stream"},
        content=b"%PDF-test-content",
    )

    dl = LibgenDownloader(cache, EnvConfig())
    paper = Paper(doi=doi, title="LibGen Success")
    result = await dl.download(paper)
    assert result is not None
    assert result.exists()
    assert result.name.endswith(".pdf")
    await dl.close()


@pytest.mark.asyncio
@respx.mock
async def test_libgen_download_search_404(cache):
    """When all mirrors return 404, download returns None."""
    doi = "10.1234/libgen-404"

    for mirror in _LIBGEN_MIRRORS:
        respx.get(
            f"{mirror}/index.php",
            params={"req": doi, "res": "25", "covers": "on", "filesuns": "all"},
        ).respond(404)

    dl = LibgenDownloader(cache, EnvConfig())
    paper = Paper(doi=doi, title="LibGen 404")
    result = await dl.download(paper)
    assert result is None
    await dl.close()


@pytest.mark.asyncio
@respx.mock
async def test_libgen_download_no_edition_id(cache):
    """When search results lack an edition ID, download returns None."""
    doi = "10.1234/libgen-no-edition"

    for mirror in _LIBGEN_MIRRORS:
        respx.get(
            f"{mirror}/index.php",
            params={"req": doi, "res": "25", "covers": "on", "filesuns": "all"},
        ).respond(
            200,
            headers={"content-type": "text/html"},
            content="<html>no edition links here</html>",
        )

    dl = LibgenDownloader(cache, EnvConfig())
    paper = Paper(doi=doi, title="LibGen No Edition")
    result = await dl.download(paper)
    assert result is None
    await dl.close()


@pytest.mark.asyncio
@respx.mock
async def test_libgen_download_no_md5(cache):
    """When edition page lacks an MD5 link, download returns None."""
    doi = "10.1234/libgen-no-md5"

    # All mirrors: search succeeds with edition ID.
    for mirror in _LIBGEN_MIRRORS:
        respx.get(
            f"{mirror}/index.php",
            params={"req": doi, "res": "25", "covers": "on", "filesuns": "all"},
        ).respond(
            200,
            headers={"content-type": "text/html"},
            content=f'<html><a href="edition.php?id={_EDITION_ID}">edition</a></html>',
        )
        # Edition page lacks an MD5 link.
        respx.get(
            f"{mirror}/edition.php",
            params={"id": _EDITION_ID},
        ).respond(200, headers={"content-type": "text/html"}, content="<html>no md5</html>")

    dl = LibgenDownloader(cache, EnvConfig())
    paper = Paper(doi=doi, title="LibGen No MD5")
    result = await dl.download(paper)
    assert result is None
    await dl.close()


@pytest.mark.asyncio
async def test_libgen_download_no_doi(cache):
    dl = LibgenDownloader(cache, EnvConfig())
    paper = Paper(title="No DOI")
    result = await dl.download(paper)
    assert result is None
    await dl.close()
