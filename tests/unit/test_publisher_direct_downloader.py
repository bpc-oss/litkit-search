"""Tests for the publisher-direct PDF downloader."""

from pathlib import Path

import pytest
import respx

from litkit.config import EnvConfig
from litkit.core.cache import MetadataCache
from litkit.core.models import Paper
from litkit.downloaders.publisher_direct import (
    PublisherDirectDownloader,
    _candidate_pdf_urls,
)


@pytest.fixture
def cache(tmp_path: Path):
    db_path = tmp_path / "test.db"
    return MetadataCache(db_path)


@pytest.mark.asyncio
async def test_publisher_direct_can_handle_with_pdf_url(cache):
    dl = PublisherDirectDownloader(cache, EnvConfig())
    paper = Paper(
        doi="10.1234/test",
        title="Test",
        pdf_url="https://example.com/paper.pdf",
    )
    assert await dl.can_handle(paper)
    await dl.close()


@pytest.mark.asyncio
async def test_publisher_direct_can_handle_without_pdf_url(cache):
    dl = PublisherDirectDownloader(cache, EnvConfig())
    paper = Paper(doi="10.1234/test", title="Test")
    # Now returns True because can_handle checks doi, not pdf_url
    assert await dl.can_handle(paper)
    await dl.close()


@pytest.mark.asyncio
@respx.mock
async def test_publisher_direct_download_success(cache):
    pdf_url = "https://example.com/paper.pdf"
    respx.get(pdf_url).respond(
        200,
        headers={"content-type": "application/pdf"},
        content=b"%PDF-test-content",
    )

    dl = PublisherDirectDownloader(cache, EnvConfig())
    paper = Paper(
        doi="10.1234/publisher-success",
        title="Publisher Direct Success",
        pdf_url=pdf_url,
    )
    result = await dl.download(paper)
    assert result is not None
    assert result.exists()
    assert result.name.endswith(".pdf")
    await dl.close()


def test_mdpi_res_urls():
    """MDPI DOIs generate working mdpi-res.com CDN URLs."""
    from litkit.downloaders.publisher_direct import _mdpi_res_urls

    # nu -> nutrients (mapped), 14/3/588 -> nutrients-14-00588
    assert _mdpi_res_urls("10.3390/nu14030588") == [
        "https://mdpi-res.com/d_attachment/nutrients/nutrients-14-00588"
        "/article_deploy/nutrients-14-00588.pdf"
    ]
    # polym -> polymers (mapped)
    assert _mdpi_res_urls("10.3390/polym15010001") == [
        "https://mdpi-res.com/d_attachment/polymers/polymers-15-00001"
        "/article_deploy/polymers-15-00001.pdf"
    ]
    # foods (abbreviation == full name) falls back to itself
    assert _mdpi_res_urls("10.3390/foods13010002") == [
        "https://mdpi-res.com/d_attachment/foods/foods-13-00002"
        "/article_deploy/foods-13-00002.pdf"
    ]
    # app -> applsci (mapped), bios -> biosensors (mapped)
    assert _mdpi_res_urls("10.3390/app14083421") == [
        "https://mdpi-res.com/d_attachment/applsci/applsci-14-03421"
        "/article_deploy/applsci-14-03421.pdf"
    ]
    assert _mdpi_res_urls("10.3390/bios15090565") == [
        "https://mdpi-res.com/d_attachment/biosensors/biosensors-15-00565"
        "/article_deploy/biosensors-15-00565.pdf"
    ]


def test_mdpi_res_urls_rejects_non_mdpi():
    from litkit.downloaders.publisher_direct import _mdpi_res_urls

    assert _mdpi_res_urls("10.1016/j.foodres.2025.117135") == []
    assert _mdpi_res_urls("10.3390/notamatching") == []
    assert _mdpi_res_urls("") == []


@pytest.mark.asyncio
@respx.mock
async def test_publisher_direct_download_404(cache):
    pdf_url = "https://example.com/missing.pdf"
    respx.get(pdf_url).respond(404)
    doi = "10.1234/publisher-404"
    # Catch-all: any generated direct-pdf URL or DOI page returns 404
    # (RSC pattern uppercases the path, hence case-insensitive)
    respx.get(url__regex=r"(?i).*publisher-404.*").respond(404)

    dl = PublisherDirectDownloader(cache, EnvConfig())
    paper = Paper(
        doi=doi,
        title="Publisher Direct 404",
        pdf_url=pdf_url,
    )
    result = await dl.download(paper)
    assert result is None
    await dl.close()


@pytest.mark.asyncio
@respx.mock
async def test_publisher_direct_download_not_pdf(cache):
    pdf_url = "https://example.com/not-pdf"
    respx.get(pdf_url).respond(
        200,
        headers={"content-type": "text/html"},
        content="<html>not a pdf</html>",
    )
    doi = "10.1234/publisher-not-pdf"
    # Catch-all for any generated direct-pdf URL or DOI page (case-insensitive for RSC)
    respx.get(url__regex=r"(?i).*publisher-not-pdf.*").respond(
        200,
        headers={"content-type": "text/html"},
        content="<html>not a pdf</html>",
    )

    dl = PublisherDirectDownloader(cache, EnvConfig())
    paper = Paper(
        doi=doi,
        title="Publisher Direct Not PDF",
        pdf_url=pdf_url,
    )
    result = await dl.download(paper)
    assert result is None
    await dl.close()


@pytest.mark.asyncio
async def test_publisher_direct_download_without_pdf_url(cache):
    dl = PublisherDirectDownloader(cache, EnvConfig())
    paper = Paper(doi="10.1234/no-url", title="No PDF URL")
    result = await dl.download(paper)
    assert result is None
    await dl.close()


@pytest.mark.asyncio
@respx.mock
async def test_publisher_direct_falls_back_to_html_pdf_links(cache):
    doi = "10.1186/test-springer-link"
    doi_url = f"https://doi.org/{doi}"
    article_url = f"https://link.springer.com/article/{doi}"
    broken_pdf_url = f"https://link.springer.com/content/pdf/{doi}.pdf"
    working_pdf_url = f"https://link.springer.com/content/pdf/{doi}_reference.pdf"

    respx.get(doi_url).respond(
        302,
        headers={"location": article_url},
    )
    respx.get(article_url).respond(
        200,
        headers={"content-type": "text/html"},
        content=(
            f'<html><head><meta name="citation_pdf_url" content="{broken_pdf_url}"/></head>'
            f'<body><a href="/content/pdf/{doi}_reference.pdf">Download PDF</a></body></html>'
        ),
    )
    respx.get(broken_pdf_url).respond(404)
    respx.get(working_pdf_url).respond(
        200,
        headers={"content-type": "application/pdf"},
        content=b"%PDF-test-content",
    )

    dl = PublisherDirectDownloader(cache, EnvConfig())
    paper = Paper(doi=doi, title="Publisher Direct HTML PDF Link")
    result = await dl.download(paper)
    assert result is not None
    assert result.exists()
    await dl.close()


@pytest.mark.asyncio
@respx.mock
async def test_publisher_direct_follows_redirect_stub(cache):
    doi = "10.1016/test-redirect-stub"
    doi_url = f"https://doi.org/{doi}"
    direct_pattern_url = "https://www.sciencedirect.com/science/article/pii/test-redirect-stub/pdf"
    landing_url = "https://linkinghub.elsevier.com/retrieve/pii/S1234567890"
    article_url = "https://www.sciencedirect.com/science/article/pii/S1234567890?via=ihub"
    pdf_url = "https://www.sciencedirect.com/science/article/pii/S1234567890/pdfft?isDTMRedir=true"

    respx.get(direct_pattern_url).respond(404)

    respx.get(doi_url).respond(
        200,
        headers={"content-type": "text/html"},
        content=(
            '<html><head><meta http-equiv="refresh" '
            f'content="0; url={landing_url}"/></head></html>'
        ),
    )
    respx.get(landing_url).respond(
        200,
        headers={"content-type": "text/html"},
        content=(
            "<html><body>"
            f'<input type="hidden" id="redirectURL" value="{article_url}"/>'
            "</body></html>"
        ),
    )
    respx.get(article_url).respond(
        200,
        headers={"content-type": "text/html"},
        content=(
            f'<html><head><meta name="citation_pdf_url" content="{pdf_url}"/></head></html>'
        ),
    )
    respx.get(pdf_url).respond(
        200,
        headers={"content-type": "application/pdf"},
        content=b"%PDF-test-content",
    )

    dl = PublisherDirectDownloader(cache, EnvConfig())
    paper = Paper(doi=doi, title="Publisher Direct Redirect Stub")
    result = await dl.download(paper)
    assert result is not None
    assert result.exists()
    await dl.close()


def test_candidate_pdf_urls_are_publisher_specific():
    ieee_paper = Paper(doi="10.1109/iecon.2017.8217285", title="IEEE Paper", year=2017)
    springer_paper = Paper(doi="10.1007/s00425-024-04376-4", title="Springer Paper", year=2024)
    wiley_paper = Paper(doi="10.1111/1750-3841.71116", title="Wiley Paper", year=2026)

    ieee_urls = _candidate_pdf_urls(ieee_paper)
    springer_urls = _candidate_pdf_urls(springer_paper)
    wiley_urls = _candidate_pdf_urls(wiley_paper)

    assert ieee_urls == []
    assert springer_urls
    assert wiley_urls == ["https://onlinelibrary.wiley.com/doi/pdf/10.1111/1750-3841.71116"]
    assert all("springer.com" in url for url in springer_urls)
