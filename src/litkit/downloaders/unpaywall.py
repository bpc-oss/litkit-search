"""Downloader for Open-Access PDFs via the Unpaywall API."""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urljoin

import httpx

from litkit.core.models import Paper
from litkit.core.ratelimit import bucket_for
from litkit.downloaders.base import Downloader
from litkit.downloaders.publisher_direct import _extract_pdf_candidates, _mdpi_res_urls

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.unpaywall.org/v2"


class UnpaywallDownloader(Downloader):
    """Resolve a DOI via the Unpaywall API and download the best OA PDF.

    Requires ``config.unpaywall_email`` to be set.
    """

    name = "unpaywall"

    async def can_handle(self, paper: Paper) -> bool:
        if not paper.doi:
            return False
        # Unpaywall requires a contact email (polite pool).
        return bool(self._config.unpaywall_email)

    async def download(self, paper: Paper) -> Path | None:
        email = self._config.unpaywall_email
        if not email or not paper.doi:
            return None

        lookup_url = f"{_BASE_URL}/{paper.doi}?email={email}"
        dest = self._cache.pdf_path(paper.id)
        dest.parent.mkdir(parents=True, exist_ok=True)

        bucket = bucket_for("unpaywall")
        await bucket.acquire()

        # Step 1 -- look up the DOI.
        try:
            resp = await self._client.get(lookup_url)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Unpaywall lookup failed (%s) for %s", exc.response.status_code, paper.doi
            )
            return None
        except httpx.RequestError as exc:
            logger.warning("Unpaywall request error for %s: %s", paper.doi, exc)
            return None

        data = resp.json()

        candidates = self._candidate_urls(data)
        # MDPI serves www.mdpi.com 403s to non-browser clients; prepend the
        # predictable mdpi-res.com CDN links so they are tried first.
        if paper.doi and paper.doi.lower().startswith("10.3390/"):
            candidates = _mdpi_res_urls(paper.doi) + candidates
        if not candidates:
            logger.info("Unpaywall found no OA PDF URL for %s", paper.doi)
            return None

        # Step 2 -- try each candidate until one yields a PDF.
        for pdf_url in candidates:
            result = await self._fetch_and_save(pdf_url, dest)
            if result is not None:
                return result

        logger.info("Unpaywall found OA locations but could not download a PDF for %s", paper.doi)
        return None

    @staticmethod
    def _candidate_urls(data: dict[str, object]) -> list[str]:
        """Return unique download or landing-page URLs from Unpaywall payload."""
        candidates: list[str] = []
        locations = []
        best = data.get("best_oa_location")
        if isinstance(best, dict):
            locations.append(best)
        oa_locations = data.get("oa_locations")
        if isinstance(oa_locations, list):
            locations.extend(loc for loc in oa_locations if isinstance(loc, dict))

        for loc in locations:
            for key in ("url_for_pdf", "pdf_url", "url", "url_for_landing_page"):
                value = loc.get(key)
                if value:
                    candidates.append(value)

        deduped: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            deduped.append(candidate)
        return deduped

    async def _fetch_and_save(self, pdf_url: str, dest: Path) -> Path | None:
        """Download a PDF directly or discover it from an OA landing page."""
        try:
            pdf_resp = await self._client.get(pdf_url)
            pdf_resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Unpaywall PDF download failed (%s) for %s",
                exc.response.status_code,
                pdf_url,
            )
            return None
        except httpx.RequestError as exc:
            logger.warning("Unpaywall PDF request error for %s: %s", pdf_url, exc)
            return None

        content_type = pdf_resp.headers.get("content-type", "")
        if "application/pdf" not in content_type:
            logger.warning(
                "Unpaywall resource at %s is not a PDF (content-type: %s)",
                pdf_url,
                content_type,
            )
            for discovered_url in _extract_pdf_candidates(str(pdf_resp.url), pdf_resp.text):
                resolved = urljoin(str(pdf_resp.url), discovered_url)
                try:
                    nested_resp = await self._client.get(resolved)
                    nested_resp.raise_for_status()
                except (httpx.HTTPStatusError, httpx.RequestError):
                    continue

                nested_type = nested_resp.headers.get("content-type", "")
                if "application/pdf" in nested_type or "application/octet-stream" in nested_type:
                    dest.write_bytes(nested_resp.content)
                    logger.info("Saved Unpaywall PDF for %s to %s", resolved, dest)
                    return dest
            return None

        dest.write_bytes(pdf_resp.content)
        logger.info("Saved Unpaywall PDF for %s to %s", pdf_url, dest)
        return dest
