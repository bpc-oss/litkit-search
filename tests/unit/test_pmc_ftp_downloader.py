"""Tests for the PubMed Central FTP downloader."""

import json
from pathlib import Path

import pytest
import respx

from litkit.config import EnvConfig
from litkit.core.cache import MetadataCache
from litkit.core.models import Paper
from litkit.downloaders.pmc_ftp import PmcFtpDownloader


@pytest.fixture
def cache(tmp_path: Path):
    db_path = tmp_path / "test.db"
    return MetadataCache(db_path)


@pytest.mark.asyncio
async def test_pmc_ftp_can_handle_with_pmcid(cache):
    dl = PmcFtpDownloader(cache, EnvConfig())
    paper = Paper(doi="10.1234/test", title="Test", extra={"pmcid": "PMC123456"})
    assert await dl.can_handle(paper)
    await dl.close()


@pytest.mark.asyncio
async def test_pmc_ftp_can_handle_with_pmid(cache):
    dl = PmcFtpDownloader(cache, EnvConfig())
    paper = Paper(doi="10.1234/test", title="Test", extra={"pmid": "12345678"})
    assert await dl.can_handle(paper)
    await dl.close()


@pytest.mark.asyncio
async def test_pmc_ftp_can_handle_without_either(cache):
    dl = PmcFtpDownloader(cache, EnvConfig())
    paper = Paper(doi="10.1234/test", title="Test")
    assert not await dl.can_handle(paper)
    await dl.close()


@pytest.mark.asyncio
async def test_pmc_ftp_can_handle_no_doi(cache):
    dl = PmcFtpDownloader(cache, EnvConfig())
    paper = Paper(title="No DOI", extra={"pmcid": "PMC123456"})
    assert not await dl.can_handle(paper)
    await dl.close()


@pytest.mark.asyncio
@respx.mock
async def test_pmc_ftp_download_with_pmcid_success(cache):
    doi = "10.1234/pmc-ftp-success"
    pmcid = "PMC123456"
    pdf_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/"

    respx.get(pdf_url).respond(
        200,
        headers={"content-type": "application/pdf"},
        content=b"%PDF-test-content",
    )

    dl = PmcFtpDownloader(cache, EnvConfig())
    paper = Paper(doi=doi, title="PMC FTP Success", extra={"pmcid": pmcid})
    result = await dl.download(paper)
    assert result is not None
    assert result.exists()
    assert result.name.endswith(".pdf")
    await dl.close()


@pytest.mark.asyncio
@respx.mock
async def test_pmc_ftp_download_404(cache):
    doi = "10.1234/pmc-ftp-404"
    pmcid = "PMC404404"
    pdf_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/"

    respx.get(pdf_url).respond(404)

    dl = PmcFtpDownloader(cache, EnvConfig())
    paper = Paper(doi=doi, title="PMC FTP 404", extra={"pmcid": pmcid})
    result = await dl.download(paper)
    assert result is None
    await dl.close()


@pytest.mark.asyncio
@respx.mock
async def test_pmc_ftp_download_not_pdf(cache):
    doi = "10.1234/pmc-ftp-not-pdf"
    pmcid = "PMC999999"
    pdf_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/"

    respx.get(pdf_url).respond(
        200,
        headers={"content-type": "text/html"},
        content="<html>not a pdf</html>",
    )

    dl = PmcFtpDownloader(cache, EnvConfig())
    paper = Paper(doi=doi, title="PMC FTP Not PDF", extra={"pmcid": pmcid})
    result = await dl.download(paper)
    assert result is None
    await dl.close()


@pytest.mark.asyncio
@respx.mock
async def test_pmc_ftp_download_with_resolve_pmcid(cache):
    """Fall back to NCBI ID converter when pmcid is not in extra."""
    doi = "10.1234/pmc-resolve-test"
    pmid = "87654321"
    resolved_pmcid = "PMC555555"
    pdf_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{resolved_pmcid}/pdf/"
    idconv_url = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"

    resolve_response = {"records": [{"pmcid": resolved_pmcid}]}
    respx.get(idconv_url, params={"ids": doi, "format": "json"}).respond(
        200,
        headers={"content-type": "application/json"},
        content=json.dumps(resolve_response).encode(),
    )
    respx.get(pdf_url).respond(
        200,
        headers={"content-type": "application/pdf"},
        content=b"%PDF-test-content",
    )

    dl = PmcFtpDownloader(cache, EnvConfig())
    paper = Paper(doi=doi, title="PMC FTP Resolve", extra={"pmid": pmid})
    result = await dl.download(paper)
    assert result is not None
    assert result.exists()
    assert result.name.endswith(".pdf")
    await dl.close()
