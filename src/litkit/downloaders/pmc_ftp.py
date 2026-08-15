"""Downloader for PubMed Central (PMC) PDFs via the PMC OA service.

Uses the PMC OA web service to resolve PMCID from DOI, then downloads
the full-text PDF.  For bulk or alternate access, point the config var
``pmc_ftp_base`` to ``ftp://ftp.ncbi.nlm.nih.gov/pub/pmc/``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from litkit.core.models import Paper
from litkit.core.ratelimit import bucket_for
from litkit.downloaders.base import Downloader

logger = logging.getLogger(__name__)

_OA_BASE = "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi"


class PmcFtpDownloader(Downloader):
    name = "pmc_ftp"

    async def can_handle(self, paper: Paper) -> bool:
        if not paper.doi:
            return False
        extra = paper.extra or {}
        if extra.get("pmcid"):
            return True
        return bool(extra.get("pmid"))

    async def download(self, paper: Paper) -> Path | None:
        if not paper.doi:
            return None
        extra = paper.extra or {}

        pmcid = extra.get("pmcid", "")
        if not pmcid:
            pmcid = await self._resolve_pmcid(paper.doi)
            if not pmcid:
                logger.info("No PMCID found for %s", paper.doi)
                return None

        url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/"
        dest = self._cache.pdf_path(paper.id)
        dest.parent.mkdir(parents=True, exist_ok=True)

        bucket = bucket_for("pmc")
        await bucket.acquire()

        try:
            response = await self._client.get(url)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning("PMC PDF GET failed (%s) for %s", exc.response.status_code, url)
            return None
        except httpx.RequestError as exc:
            logger.warning("PMC request error for %s: %s", url, exc)
            return None

        content_type = response.headers.get("content-type", "")
        if "application/pdf" not in content_type and "application/octet-stream" not in content_type:
            logger.warning("PMC response for %s is not a PDF (content-type: %s)", url, content_type)
            return None

        dest.write_bytes(response.content)
        logger.info("Saved PMC PDF for %s to %s", paper.doi, dest)
        return dest

    async def _resolve_pmcid(self, doi: str) -> str | None:
        """Resolve a DOI to a PMCID via the NCBI ID converter."""
        url = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
        params = {"ids": doi, "format": "json"}
        bucket = bucket_for("pmc")
        await bucket.acquire()
        try:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            records = data.get("records") or []
            if records:
                return records[0].get("pmcid") or None
        except Exception:
            logger.debug("PMC ID conversion failed for %s", doi)
        return None
