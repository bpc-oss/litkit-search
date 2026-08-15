"""Download PDFs from Anna's Archive by DOI search.

Scrapes the Anna's Archive search page for a matching MD5 entry, follows it
to the details page, and extracts a downloadable PDF link.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import httpx

from litkit.core.models import Paper
from litkit.core.ratelimit import bucket_for
from litkit.downloaders._dns import ensure_resolved
from litkit.downloaders.base import Downloader

logger = logging.getLogger(__name__)

# Base URLs to try in order.
_BASES = [
    "https://annas-archive.gs",
    "https://annas-archive.org",
    "https://annas-archive.se",
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

# Match MD5-linked entries in the search results page.
_MD5_RE = re.compile(r'href="(/md5/[a-f0-9]{32})"', re.IGNORECASE)

# Match Anna's Archive internal download endpoints (/d/... or /dl/...).
_DOWNLOAD_RE = re.compile(r'href="(/d(?:l)?/[^"]+)"', re.IGNORECASE)

# Match direct PDF URLs (e.g. IPFS / cloudflare gateway links).
_PDF_URL_RE = re.compile(r'href="(https?://[^"]+\.pdf[^"]*)"', re.IGNORECASE)


class AnnasArchiveDownloader(Downloader):
    """Download PDFs from Anna's Archive.

    Search the public-facing web site by DOI, find an MD5 link to the
    details page, then scrape a downloadable PDF URL.
    """

    name = "annas_archive"

    async def can_handle(self, paper: Paper) -> bool:
        """Can handle any paper that has a DOI."""
        return bool(paper.doi)

    async def download(self, paper: Paper) -> Path | None:
        """Download the PDF for *paper* via Anna's Archive.

        Returns the local cached path on success, or ``None`` if the
        paper is not found / a network error occurred.
        """
        ensure_resolved()

        doi = paper.doi
        if not doi:
            return None

        dest = self._cache.pdf_path(paper.id)
        dest.parent.mkdir(parents=True, exist_ok=True)

        for base in _BASES:
            md5_path = await self._search(doi, base)
            if md5_path is None:
                continue

            pdf_url = await self._fetch_download_url(md5_path, base)
            if pdf_url is None:
                continue

            # Download the actual PDF.
            bucket = bucket_for("annas_archive")
            await bucket.acquire()

            try:
                pdf_resp = await self._client.get(pdf_url, headers=_HEADERS)
                pdf_resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "Anna's Archive PDF download returned %s for %s",
                    exc.response.status_code,
                    doi,
                )
                continue
            except httpx.RequestError as exc:
                logger.warning(
                    "Anna's Archive PDF download request failed for %s: %s",
                    doi,
                    exc,
                )
                continue

            dest.write_bytes(pdf_resp.content)
            logger.info("Saved Anna's Archive PDF for %s from %s to %s", doi, base, dest)
            return dest

        logger.info("All Anna's Archive bases exhausted for %s", doi)
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _search(self, doi: str, base: str) -> str | None:
        """Search Anna's Archive by DOI and return the first MD5 path."""
        bucket = bucket_for("annas_archive")
        await bucket.acquire()

        search_url = f"{base}/search?q={doi}"
        logger.debug("Searching Anna's Archive: %s", search_url)

        try:
            resp = await self._client.get(search_url, headers=_HEADERS)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.debug(
                "Anna's Archive search returned %s for %s",
                exc.response.status_code,
                doi,
            )
            return None
        except httpx.RequestError as exc:
            logger.debug(
                "Anna's Archive search connection failed for %s: %s",
                doi,
                exc,
            )
            return None

        m = _MD5_RE.search(resp.text)
        if m is None:
            logger.debug("No MD5 link found in search results for %s", doi)
            return None

        logger.debug("Found MD5 link for %s: %s", doi, m.group(1))
        return m.group(1)

    async def _fetch_download_url(self, md5_path: str, base: str) -> str | None:
        """Fetch the details page and extract a downloadable PDF URL."""
        bucket = bucket_for("annas_archive")
        await bucket.acquire()

        details_url = f"{base}{md5_path}"
        logger.debug("Fetching Anna's Archive details page: %s", details_url)

        try:
            resp = await self._client.get(details_url, headers=_HEADERS)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.debug(
                "Anna's Archive details page returned %s for %s",
                exc.response.status_code,
                details_url,
            )
            return None
        except httpx.RequestError as exc:
            logger.debug(
                "Anna's Archive details page connection failed for %s: %s",
                details_url,
                exc,
            )
            return None

        url = self._extract_pdf_url(resp.text)
        if url is None:
            logger.debug("No download link found on %s", details_url)
            return None

        # Resolve relative URLs against the base domain.
        if url.startswith("/"):
            url = f"{base}{url}"

        logger.debug("Found PDF URL on details page: %s", url)
        return url

    @staticmethod
    def _extract_pdf_url(html: str) -> str | None:
        """Extract a downloadable PDF URL from the details page HTML.

        Preference order:
          1. Direct ``.pdf`` links (IPFS gateways, Cloudflare etc.).
          2. Anna's Archive download endpoints (``/d/...``, ``/dl/...``).
        """
        # Prefer direct PDF links.
        m = _PDF_URL_RE.search(html)
        if m is not None:
            return m.group(1)

        # Fall back to internal download endpoints.
        m = _DOWNLOAD_RE.search(html)
        if m is not None:
            return m.group(1)

        return None
