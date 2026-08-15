"""Tests for the Sci-Hub downloader."""

from pathlib import Path

import pytest
import respx

from litkit.config import EnvConfig
from litkit.core.cache import MetadataCache
from litkit.core.models import Paper
from litkit.downloaders.scihub import _SCI_HUB_DOMAINS, SciHubDownloader


@pytest.fixture
def cache(tmp_path: Path):
    db_path = tmp_path / "test.db"
    return MetadataCache(db_path)


@pytest.mark.asyncio
async def test_scihub_can_handle_with_doi(cache):
    dl = SciHubDownloader(cache, EnvConfig())
    paper = Paper(doi="10.1234/test", title="Test")
    assert await dl.can_handle(paper)
    await dl.close()


@pytest.mark.asyncio
async def test_scihub_can_handle_without_doi(cache):
    dl = SciHubDownloader(cache, EnvConfig())
    paper = Paper(title="No DOI")
    assert not await dl.can_handle(paper)
    await dl.close()


@pytest.mark.asyncio
@respx.mock
async def test_scihub_download_direct_pdf(cache):
    doi = "10.1234/scihub-direct"
    respx.get(f"{_SCI_HUB_DOMAINS[0]}/{doi}").respond(
        200,
        headers={"content-type": "application/pdf"},
        content=b"%PDF-test-content",
    )

    dl = SciHubDownloader(cache, EnvConfig())
    paper = Paper(doi=doi, title="Sci-Hub Direct PDF")
    result = await dl.download(paper)
    assert result is not None
    assert result.exists()
    assert result.name.endswith(".pdf")
    await dl.close()


@pytest.mark.asyncio
@respx.mock
async def test_scihub_download_via_embed(cache):
    doi = "10.1234/scihub-embed"
    pdf_download_url = "https://sci-hub.se/downloads/test.pdf"

    # HTML with iframe pointing to a PDF (protocol-relative URL).
    html = (
        "<html><head></head><body>"
        "<div id='article'>" + "A" * 600 + "</div>"
        '<iframe src="//sci-hub.se/downloads/test.pdf" width="100%" height="1000"></iframe>'
        "</body></html>"
    )

    respx.get(f"{_SCI_HUB_DOMAINS[0]}/{doi}").respond(
        200,
        headers={"content-type": "text/html"},
        content=html,
    )
    respx.get(pdf_download_url).respond(
        200,
        headers={"content-type": "application/pdf"},
        content=b"%PDF-test-content",
    )

    dl = SciHubDownloader(cache, EnvConfig())
    paper = Paper(doi=doi, title="Sci-Hub Embed PDF")
    result = await dl.download(paper)
    assert result is not None
    assert result.exists()
    assert result.name.endswith(".pdf")
    await dl.close()


@pytest.mark.asyncio
@respx.mock
async def test_scihub_download_all_404(cache):
    doi = "10.1234/scihub-all-404"
    for domain in _SCI_HUB_DOMAINS:
        respx.get(f"{domain}/{doi}").respond(404)

    dl = SciHubDownloader(cache, EnvConfig())
    paper = Paper(doi=doi, title="Sci-Hub All 404")
    result = await dl.download(paper)
    assert result is None
    await dl.close()


@pytest.mark.asyncio
@respx.mock
async def test_scihub_download_captcha(cache):
    doi = "10.1234/scihub-captcha"
    for domain in _SCI_HUB_DOMAINS:
        respx.get(f"{domain}/{doi}").respond(
            200,
            headers={"content-type": "text/html"},
            content="<html>captcha challenge page</html>",
        )

    dl = SciHubDownloader(cache, EnvConfig())
    paper = Paper(doi=doi, title="Sci-Hub CAPTCHA")
    result = await dl.download(paper)
    assert result is None
    await dl.close()


@pytest.mark.asyncio
@respx.mock
async def test_scihub_download_fallback_domain(cache):
    doi = "10.1234/scihub-fallback"
    # First domain fails.
    respx.get(f"{_SCI_HUB_DOMAINS[0]}/{doi}").respond(404)
    # Second domain succeeds.
    respx.get(f"{_SCI_HUB_DOMAINS[1]}/{doi}").respond(
        200,
        headers={"content-type": "application/pdf"},
        content=b"%PDF-test-content",
    )

    dl = SciHubDownloader(cache, EnvConfig())
    paper = Paper(doi=doi, title="Sci-Hub Fallback")
    result = await dl.download(paper)
    assert result is not None
    assert result.exists()
    assert result.name.endswith(".pdf")
    await dl.close()

def test_scihub_domains_order():
    """Dead sci-hub.se is last; working mirrors (ee/sg) come first."""
    assert _SCI_HUB_DOMAINS[0] == "https://sci-hub.ee"
    assert _SCI_HUB_DOMAINS[1] == "https://sci-hub.sg"
    assert _SCI_HUB_DOMAINS[-1] == "https://sci-hub.se"


@pytest.mark.asyncio
@respx.mock
async def test_scihub_sends_browser_headers(cache):
    """Article requests carry a browser UA and a Referer."""
    doi = "10.1234/scihub-headers"
    url = f"{_SCI_HUB_DOMAINS[0]}/{doi}"
    respx.get(url).respond(
        200,
        headers={"content-type": "application/pdf"},
        content=b"%PDF-test-content",
    )
    dl = SciHubDownloader(cache, EnvConfig())
    result = await dl.download(Paper(doi=doi, title="Headers"))
    assert result is not None
    req = respx.calls[0].request
    assert "Mozilla/5.0" in req.headers.get("user-agent", "")
    assert req.headers.get("referer", "").startswith(_SCI_HUB_DOMAINS[0])
    await dl.close()


@pytest.mark.asyncio
@respx.mock
async def test_scihub_article_with_cloudflare_beacon_is_not_captcha(cache):
    """Real article pages embedding a Cloudflare Insights beacon must not
    be misclassified as a CAPTCHA page."""
    doi = "10.1234/scihub-beacon"
    url = f"{_SCI_HUB_DOMAINS[0]}/{doi}"
    article_html = (
        "<html><head><title>Sci-Hub | Real Article</title></head><body>"
        "<div id='article'>" + "A" * 900 + "</div>"
        '<iframe src="//cdn.example.com/paper.pdf"></iframe>'
        '<script src="https://static.cloudflareinsights.com/beacon.min.js"></script>'
        "</body></html>"
    )
    respx.get(url).respond(
        200,
        headers={"content-type": "text/html"},
        content=article_html,
    )
    respx.get("https://cdn.example.com/paper.pdf").respond(
        200,
        headers={"content-type": "application/pdf"},
        content=b"%PDF-test-content",
    )
    dl = SciHubDownloader(cache, EnvConfig())
    result = await dl.download(Paper(doi=doi, title="Beacon"))
    assert result is not None
    assert result.exists()
    await dl.close()
