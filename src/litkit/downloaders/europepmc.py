"""Downloader for PDFs from Europe PMC."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import httpx

from litkit.core.models import Paper
from litkit.downloaders.base import Downloader

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_PMC_PDF_PATTERN = "https://europepmc.org/articles/{pmcid}/pdf"

# Normalise PMCID values (strip optional "PMC" prefix).
_PMCID_RE = re.compile(r"^PMC?(\d+)$", re.IGNORECASE)


def _normalise_pmcid(raw: str) -> str | None:
    """Return standard ``PMCxxxxx`` form or None if not parseable."""
    m = _PMCID_RE.match(raw.strip())
    if m:
        return f"PMC{m.group(1)}"
    return None


def _get_pmcid(paper: Paper) -> str | None:
    """Look for a PMCID in ``paper.extra``."""
    if not paper.extra:
        return None
    raw = paper.extra.get("pmcid") or paper.extra.get("pmc_id") or ""
    if not raw:
        return None
    return _normalise_pmcid(raw)


class EuropePmcDownloader(Downloader):
    """Download PDFs from Europe PMC via the REST search API or direct URL.

    Tries two strategies in order:

    1. Search by DOI and check for a ``pdfUrl`` in the response.
    2. If the paper has a PMCID, construct the direct PDF URL.
    """

    name = "europepmc"

    async def can_handle(self, paper: Paper) -> bool:
        return bool(paper.doi) or _get_pmcid(paper) is not None

    async def download(self, paper: Paper) -> Path | None:
        dest = self._cache.pdf_path(paper.id)
        dest.parent.mkdir(parents=True, exist_ok=True)

        # Strategy 1 -- search by DOI.
        if paper.doi:
            result = await self._download_by_doi(paper.doi, dest)
            if result is not None:
                return result

        # Strategy 2 -- direct PMCID URL.
        pmcid = _get_pmcid(paper)
        if pmcid:
            result = await self._download_by_pmcid(pmcid, dest)
            if result is not None:
                return result

        return None

    # ---- internal helpers --------------------------------------------------

    async def _download_by_doi(self, doi: str, dest: Path) -> Path | None:
        params = {"query": f"DOI:{doi}", "format": "json", "pageSize": "1"}
        try:
            resp = await self._client.get(_SEARCH_URL, params=params)
            resp.raise_for_status()
        except httpx.RequestError as exc:
            logger.warning("Europe PMC search request error for DOI %s: %s", doi, exc)
            return None
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Europe PMC search failed (%s) for DOI %s", exc.response.status_code, doi
            )
            return None

        data = resp.json()
        results = (data.get("resultList") or {}).get("result") or []
        if not results:
            logger.info("Europe PMC search returned no results for DOI %s", doi)
            return None

        r = results[0]
        pdf_url = r.get("pdfUrl") or r.get("pdf_link") or ""
        if pdf_url:
            return await self._save_pdf(pdf_url, doi, dest)

        # No direct pdfUrl — try PMCID-based URL as fallback.
        pmcid = _normalise_pmcid(r.get("pmcid") or "")
        if pmcid:
            pdf_url = _PMC_PDF_PATTERN.format(pmcid=pmcid)
            logger.debug("Europe PMC fallback to PMCID URL for %s: %s", doi, pdf_url)
            return await self._save_pdf(pdf_url, doi, dest)

        logger.info("Europe PMC result for DOI %s has no pdfUrl or pmcid", doi)
        return None

    async def _download_by_pmcid(self, pmcid: str, dest: Path) -> Path | None:
        pdf_url = _PMC_PDF_PATTERN.format(pmcid=pmcid)
        return await self._save_pdf(pdf_url, pmcid, dest)

    async def _save_pdf(self, url: str, label: str, dest: Path) -> Path | None:
        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning("Europe PMC PDF GET failed (%s) for %s", exc.response.status_code, url)
            return None
        except httpx.RequestError as exc:
            logger.warning("Europe PMC PDF request error for %s: %s", url, exc)
            return None

        content_type = resp.headers.get("content-type", "")
        if "application/pdf" not in content_type:
            logger.warning(
                "Europe PMC resource at %s is not a PDF (content-type: %s)",
                url,
                content_type,
            )
            return None

        dest.write_bytes(resp.content)
        logger.info("Saved Europe PMC PDF for %s to %s", label, dest)
        return dest
