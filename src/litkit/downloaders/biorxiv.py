"""Downloader for bioRxiv/medRxiv PDFs via the direct PDF endpoint.

bioRxiv/medRxiv serve PDFs at predictable URLs based on the DOI:
  https://www.biorxiv.org/content/{doi}.full.pdf
  https://www.medrxiv.org/content/{doi}.full.pdf
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from litkit.core.models import Paper
from litkit.core.ratelimit import bucket_for
from litkit.downloaders.base import Downloader

logger = logging.getLogger(__name__)


class BiorxivDownloader(Downloader):
    name = "biorxiv"

    async def can_handle(self, paper: Paper) -> bool:
        if not paper.doi:
            return False
        server = (paper.extra or {}).get("server", "")
        return server in ("biorxiv", "medrxiv")

    async def download(self, paper: Paper) -> Path | None:
        if not paper.doi:
            return None
        server = (paper.extra or {}).get("server", "biorxiv")
        url = f"https://www.{server}.org/content/{paper.doi}.full.pdf"
        dest = self._cache.pdf_path(paper.id)
        dest.parent.mkdir(parents=True, exist_ok=True)

        bucket = bucket_for("biorxiv")
        await bucket.acquire()

        try:
            response = await self._client.get(url)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning("%s PDF GET failed (%s) for %s", server, exc.response.status_code, url)
            return None
        except httpx.RequestError as exc:
            logger.warning("%s request error for %s: %s", server, url, exc)
            return None

        content_type = response.headers.get("content-type", "")
        if "application/pdf" not in content_type:
            logger.warning(
                "%s response for %s is not a PDF (content-type: %s)",
                server,
                url,
                content_type,
            )
            return None

        dest.write_bytes(response.content)
        logger.info("Saved %s PDF for %s to %s", server, paper.doi, dest)
        return dest
