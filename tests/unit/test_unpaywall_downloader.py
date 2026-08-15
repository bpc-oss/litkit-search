"""Tests for the Unpaywall downloader."""

from pathlib import Path

import pytest
import respx

from litkit.config import EnvConfig
from litkit.core.cache import MetadataCache
from litkit.core.models import Paper
from litkit.downloaders.unpaywall import UnpaywallDownloader

_BASE_URL = "https://api.unpaywall.org/v2"


@pytest.fixture
def cache(tmp_path: Path):
    db_path = tmp_path / "test.db"
    return MetadataCache(db_path)


@pytest.mark.asyncio
async def test_unpaywall_can_handle_with_email(cache):
    dl = UnpaywallDownloader(cache, EnvConfig(unpaywall_email="test@example.com"))
    paper = Paper(doi="10.1234/test", title="Test")
    assert await dl.can_handle(paper)
    await dl.close()


@pytest.mark.asyncio
async def test_unpaywall_can_handle_without_email(cache):
    dl = UnpaywallDownloader(cache, EnvConfig())
    paper = Paper(doi="10.1234/test", title="Test")
    assert not await dl.can_handle(paper)
    await dl.close()


@pytest.mark.asyncio
async def test_unpaywall_can_handle_no_doi(cache):
    dl = UnpaywallDownloader(cache, EnvConfig(unpaywall_email="test@example.com"))
    paper = Paper(title="No DOI")
    assert not await dl.can_handle(paper)
    await dl.close()


@pytest.mark.asyncio
@respx.mock
async def test_unpaywall_download_success(cache):
    doi = "10.1234/unpaywall-success"
    pdf_url = "https://example.com/paper.pdf"
    lookup_url = f"{_BASE_URL}/{doi}?email=test@example.com"

    respx.get(lookup_url).respond(
        200,
        headers={"content-type": "application/json"},
        content=b'{"best_oa_location": {"is_best": true, "pdf_url": "' + pdf_url.encode() + b'"}}',
    )
    respx.get(pdf_url).respond(
        200,
        headers={"content-type": "application/pdf"},
        content=b"%PDF-test-content",
    )

    dl = UnpaywallDownloader(cache, EnvConfig(unpaywall_email="test@example.com"))
    paper = Paper(doi=doi, title="Unpaywall Success")
    result = await dl.download(paper)
    assert result is not None
    assert result.exists()
    assert result.name.endswith(".pdf")
    await dl.close()


@pytest.mark.asyncio
@respx.mock
async def test_unpaywall_download_mdpi_prefers_cdn(cache):
    """MDPI DOIs try the mdpi-res.com CDN before www.mdpi.com links."""
    doi = "10.3390/nu14030588"
    lookup_url = f"{_BASE_URL}/{doi}?email=test@example.com"
    mdpi_www = "https://www.mdpi.com/2072-6643/14/3/588/pdf"
    mdpi_cdn = (
        "https://mdpi-res.com/d_attachment/nutrients/nutrients-14-00588"
        "/article_deploy/nutrients-14-00588.pdf"
    )

    respx.get(lookup_url).respond(
        200,
        headers={"content-type": "application/json"},
        content=(
            b'{"best_oa_location": {"url_for_pdf": "'
            + mdpi_www.encode()
            + b'"}}'
        ),
    )
    # www.mdpi.com 403s non-browser clients
    respx.get(mdpi_www).respond(403)
    respx.get(mdpi_cdn).respond(
        200,
        headers={"content-type": "application/pdf"},
        content=b"%PDF-test-content",
    )

    dl = UnpaywallDownloader(cache, EnvConfig(unpaywall_email="test@example.com"))
    paper = Paper(doi=doi, title="MDPI OA")
    result = await dl.download(paper)
    assert result is not None
    assert result.exists()
    urls = [str(r.request.url) for r in respx.calls]
    assert mdpi_cdn in urls
    assert mdpi_www not in urls
    await dl.close()


@pytest.mark.asyncio
@respx.mock
async def test_unpaywall_download_404_lookup(cache):
    doi = "10.1234/unpaywall-404"
    lookup_url = f"{_BASE_URL}/{doi}?email=test@example.com"

    respx.get(lookup_url).respond(404)

    dl = UnpaywallDownloader(cache, EnvConfig(unpaywall_email="test@example.com"))
    paper = Paper(doi=doi, title="Unpaywall 404")
    result = await dl.download(paper)
    assert result is None
    await dl.close()


@pytest.mark.asyncio
@respx.mock
async def test_unpaywall_download_not_pdf(cache):
    doi = "10.1234/unpaywall-not-pdf"
    pdf_url = "https://example.com/not-pdf"
    lookup_url = f"{_BASE_URL}/{doi}?email=test@example.com"

    respx.get(lookup_url).respond(
        200,
        headers={"content-type": "application/json"},
        content=b'{"best_oa_location": {"is_best": true, "pdf_url": "' + pdf_url.encode() + b'"}}',
    )
    respx.get(pdf_url).respond(
        200,
        headers={"content-type": "text/html"},
        content="<html>not a pdf</html>",
    )

    dl = UnpaywallDownloader(cache, EnvConfig(unpaywall_email="test@example.com"))
    paper = Paper(doi=doi, title="Unpaywall Not PDF")
    result = await dl.download(paper)
    assert result is None
    await dl.close()


@pytest.mark.asyncio
@respx.mock
async def test_unpaywall_download_oa_locations_fallback(cache):
    """Fall back to oa_locations when best_oa_location has no pdf_url."""
    doi = "10.1234/unpaywall-fallback"
    pdf_url = "https://example.com/oa-paper.pdf"
    lookup_url = f"{_BASE_URL}/{doi}?email=test@example.com"

    respx.get(lookup_url).respond(
        200,
        headers={"content-type": "application/json"},
        content=(
            b'{"best_oa_location": null,'
            b' "oa_locations": [{"pdf_url": "' + pdf_url.encode() + b'"}]}'
        ),
    )
    respx.get(pdf_url).respond(
        200,
        headers={"content-type": "application/pdf"},
        content=b"%PDF-test-content",
    )

    dl = UnpaywallDownloader(cache, EnvConfig(unpaywall_email="test@example.com"))
    paper = Paper(doi=doi, title="Unpaywall Fallback")
    result = await dl.download(paper)
    assert result is not None
    assert result.exists()
    assert result.name.endswith(".pdf")
    await dl.close()


@pytest.mark.asyncio
@respx.mock
async def test_unpaywall_download_uses_url_for_pdf(cache):
    doi = "10.1234/unpaywall-url-for-pdf"
    pdf_url = "https://example.com/url-for-pdf.pdf"
    lookup_url = f"{_BASE_URL}/{doi}?email=test@example.com"

    respx.get(lookup_url).respond(
        200,
        headers={"content-type": "application/json"},
        content=(
            b'{"best_oa_location": {"is_best": true, "url_for_pdf": "'
            + pdf_url.encode()
            + b'"}}'
        ),
    )
    respx.get(pdf_url).respond(
        200,
        headers={"content-type": "application/pdf"},
        content=b"%PDF-test-content",
    )

    dl = UnpaywallDownloader(cache, EnvConfig(unpaywall_email="test@example.com"))
    paper = Paper(doi=doi, title="Unpaywall URL for PDF")
    result = await dl.download(paper)
    assert result is not None
    assert result.exists()
    await dl.close()


@pytest.mark.asyncio
@respx.mock
async def test_unpaywall_download_from_landing_page_html(cache):
    doi = "10.1234/unpaywall-landing-page"
    landing_url = "https://example.com/article"
    pdf_url = "https://example.com/content/pdf/test_reference.pdf"
    lookup_url = f"{_BASE_URL}/{doi}?email=test@example.com"

    respx.get(lookup_url).respond(
        200,
        headers={"content-type": "application/json"},
        content=(
            b'{"best_oa_location": {"is_best": true, "url": "'
            + landing_url.encode()
            + b'"}}'
        ),
    )
    respx.get(landing_url).respond(
        200,
        headers={"content-type": "text/html"},
        content=(
            '<html><head><meta name="citation_pdf_url" content="https://example.com/broken.pdf"/></head>'
            '<body><a href="/content/pdf/test_reference.pdf">Download PDF</a></body></html>'
        ),
    )
    respx.get("https://example.com/broken.pdf").respond(404)
    respx.get(pdf_url).respond(
        200,
        headers={"content-type": "application/pdf"},
        content=b"%PDF-test-content",
    )

    dl = UnpaywallDownloader(cache, EnvConfig(unpaywall_email="test@example.com"))
    paper = Paper(doi=doi, title="Unpaywall Landing Page")
    result = await dl.download(paper)
    assert result is not None
    assert result.exists()
    await dl.close()
