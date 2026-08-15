"""Download PDFs from Sci-Hub mirrors."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from urllib.parse import urljoin

import httpx

from litkit.core.models import Paper
from litkit.downloaders._dns import ensure_resolved
from litkit.downloaders.base import Downloader

# Match <meta name="citation_pdf_url" content="...">
_CITATION_PDF_URL_RE = re.compile(
    r'<meta\s+name=[\'"]citation_pdf_url[\'"]\s+content=[\'"]([^\'"]+)[\'"]',
    re.IGNORECASE,
)

logger = logging.getLogger(__name__)

# Sci-Hub base URLs to try (in order of observed reachability).
# sci-hub.ee serves real article pages to browser-like requests; sci-hub.sg
# is the current redirect target of .ru/.box; sci-hub.se is dead (NXDOMAIN
# on every DoH provider) so it is tried last.
_SCI_HUB_DOMAINS = [
    "https://sci-hub.ee",
    "https://sci-hub.sg",
    "https://sci-hub.ru",
    "https://sci-hub.st",
    "https://sci-hub.box",
    "https://sci-hub.shop",
    "https://sci-hub.ren",
    "https://sci-hub.se",
]

# Browser-like headers: DDoS-Guard serves a CAPTCHA to bare httpx clients
# but lets requests with a realistic User-Agent and Referer through.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# If the response body contains any of these (lower-cased) we assume
# a CAPTCHA / anti-bot page was served instead of the real article.
# Note: plain "cloudflare" / "please wait" / "just a moment" are too
# broad — real article pages embed Cloudflare Insights beacons and
# "please wait" copy.  Match on the actual challenge fingerprints.
_CAPTCHA_HINTS = (
    "altcha",
    "ddos-guard",
    "checking your browser before accessing",
    "challenge-platform",
    "attention required",
    "are you a robot",
    "你是机器人",
    "captcha",
)

# Match <iframe> or <embed> elements whose src looks like a PDF path.
_EMBED_RE = re.compile(
    r'<(?:iframe|embed)\s[^>]*?src\s*=\s*["\'](?P<src>[^"\']+?)["\']',
    re.IGNORECASE,
)


def _looks_like_captcha(html: str) -> bool:
    """Heuristic check for CAPTCHA / challenge pages."""
    lower = html.lower()
    for hint in _CAPTCHA_HINTS:
        if hint in lower:
            return True
    # Very short pages are usually error/challenge pages.
    return len(html) < 500


def _resolve_pdf_url(base: str, html: str) -> str | None:
    """Parse the HTML for a PDF embed/iframe and return an absolute URL."""
    for m in _EMBED_RE.finditer(html):
        src = m.group("src")
        if not src:
            continue
        # Avoid data URIs and JavaScript.
        if src.startswith("data:") or src.startswith("javascript:"):
            continue
        # URL-join handles protocol-relative (//...) and relative paths.
        if src.startswith("//"):
            # Sci-Hub often uses protocol-relative URLs.
            from urllib.parse import urlparse

            parsed = urlparse(base)
            src = f"{parsed.scheme}:{src}"
        else:
            src = urljoin(base, src)
        return src
    return None


class SciHubDownloader(Downloader):
    """Download PDFs from Sci-Hub mirrors.

    Tries multiple well-known Sci-Hub domains and parses the article page
    for an embedded PDF URL.
    """

    name = "scihub"

    async def can_handle(self, paper: Paper) -> bool:
        return bool(paper.doi)

    async def download(self, paper: Paper) -> Path | None:
        ensure_resolved()

        doi = paper.doi
        if not doi:
            return None

        dest = self._cache.pdf_path(paper.id)
        dest.parent.mkdir(parents=True, exist_ok=True)

        for base_url in _SCI_HUB_DOMAINS:
            result = await self._try_domain(base_url, doi, dest)
            if result is not None:
                return result

        logger.info("All Sci-Hub domains exhausted for %s", doi)
        return None

    async def _try_domain(self, base_url: str, doi: str, dest: Path) -> Path | None:
        article_url = f"{base_url}/{doi}"
        logger.debug("Trying Sci-Hub: %s", article_url)

        headers = dict(_HEADERS)
        headers["Referer"] = f"{base_url}/"

        try:
            resp = await self._client.get(article_url, headers=headers)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.debug("Sci-Hub %s returned %s", article_url, exc.response.status_code)
            return None
        except httpx.RequestError as exc:
            logger.debug("Sci-Hub %s request error: %s", article_url, exc)
            return None

        # If the response is already a PDF, we are done.
        content_type = resp.headers.get("content-type", "")
        if "application/pdf" in content_type:
            dest.write_bytes(resp.content)
            logger.info("Saved Sci-Hub PDF (direct) for %s to %s", doi, dest)
            return dest

        # Otherwise, parse the HTML for a PDF URL.
        html = resp.text

        # Strategy 1: citation_pdf_url meta tag — bypasses Altcha CAPTCHA.
        m = _CITATION_PDF_URL_RE.search(html)
        if m:
            pdf_url = urljoin(str(resp.url), m.group(1))
            logger.debug("Sci-Hub citation_pdf_url -> %s", pdf_url)
            result = await self._download_pdf(pdf_url, dest)
            if result is not None:
                return result

        # Strategy 2: iframe/embed element.
        if _looks_like_captcha(html):
            logger.debug("Sci-Hub %s returned a CAPTCHA page, skipping", article_url)
            return None

        # Use the final redirect URL (e.g. sci-net.xyz) as base, not the
        # original domain — this avoids DDoS-Guard challenges on storage.
        actual_base = str(resp.url)
        pdf_url = _resolve_pdf_url(actual_base, html)
        if pdf_url is None:
            logger.debug("No PDF embed found in Sci-Hub page %s", article_url)
            return None

        # Strategy 2 continued — download from iframe/embed URL.
        return await self._download_pdf(pdf_url, dest)

    async def _download_pdf(self, pdf_url: str, dest: Path) -> Path | None:
        """Download PDF from *pdf_url* and save to *dest*."""
        # The CDN (e.g. sci.bban.top) expects browser-like headers.
        try:
            pdf_resp = await self._client.get(pdf_url, headers=_HEADERS)
            pdf_resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.debug("Sci-Hub PDF GET failed (%s) for %s", exc.response.status_code, pdf_url)
            return None
        except httpx.RequestError as exc:
            logger.debug("Sci-Hub PDF request error for %s: %s", pdf_url, exc)
            return None

        pdf_type = pdf_resp.headers.get("content-type", "")
        if "application/pdf" not in pdf_type:
            logger.debug("Sci-Hub resource at %s is not PDF (content-type: %s)", pdf_url, pdf_type)
            return None

        dest.write_bytes(pdf_resp.content)
        logger.info("Saved Sci-Hub PDF to %s", dest)
        return dest
