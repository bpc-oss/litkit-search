"""Downloader for arXiv.org PDFs via the direct PDF endpoint."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import httpx

from litkit.core.models import Paper
from litkit.core.ratelimit import bucket_for
from litkit.downloaders.base import Downloader

logger = logging.getLogger(__name__)

# Match bare arXiv IDs (with or without version suffix).
_ARXIV_ID_RE = re.compile(
    r"(?:arxiv:)?"
    r"(?P<id>\d{4}\.\d{4,5}(v\d+)?"
    r"|[a-z-]+/\d{7,8}(v\d+)?)"
    r"\.pdf$",
    re.IGNORECASE,
)


def _extract_arxiv_id(paper: Paper) -> str | None:
    """Try to extract a stable arXiv ID from the paper metadata.

    Priority:
    1. ``paper.extra["arxiv_id"]``
    2. The arXiv ID embedded in *paper.pdf_url*
    3. ``paper.id`` if it looks like an arXiv ID (not a DOI)
    """
    # 1 -- explicit extra field.
    if paper.extra and "arxiv_id" in paper.extra:
        raw = paper.extra["arxiv_id"]
        m = _ARXIV_ID_RE.search(raw)
        if m:
            return m.group("id")
        # Strip leading "arxiv:" if present.
        return raw.removeprefix("arxiv:").strip()

    # 2 -- extract from pdf_url.
    if paper.pdf_url:
        m = re.search(r"arxiv\.org/(?:pdf|abs)/([^/?#]+)", paper.pdf_url)
        if m:
            return m.group(1).removesuffix(".pdf")

    # 3 -- paper.id might be a raw arXiv ID (only if it does not look like a DOI).
    if paper.id and not paper.id.startswith("10."):
        m = _ARXIV_ID_RE.search(paper.id)
        if m:
            return m.group("id")
        # Some sources store the bare ID without a version.
        if re.match(r"^\d{4}\.\d{4,5}$", paper.id):
            return paper.id
        if re.match(r"^[a-z-]+\d{7,8}$", paper.id):
            return paper.id

    return None


class ArxivDownloader(Downloader):
    """Download PDFs directly from ``https://arxiv.org/pdf/{id}.pdf``."""

    name = "arxiv"

    async def can_handle(self, paper: Paper) -> bool:
        source = (paper.source or "").lower()
        if source == "arxiv" or "arxiv" in source:
            return True
        # Also handle if we can confidently resolve an arXiv ID.
        return _extract_arxiv_id(paper) is not None

    async def download(self, paper: Paper) -> Path | None:
        arxiv_id = _extract_arxiv_id(paper)
        if arxiv_id is None:
            logger.warning("No arXiv ID found for %s", paper.doi or paper.id)
            return None

        url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
        dest = self._cache.pdf_path(paper.id)
        dest.parent.mkdir(parents=True, exist_ok=True)

        bucket = bucket_for("arxiv")
        await bucket.acquire()

        try:
            response = await self._client.get(url)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning("arXiv GET failed (%s) for %s: %s", exc.response.status_code, url, exc)
            return None
        except httpx.RequestError as exc:
            logger.warning("arXiv request error for %s: %s", url, exc)
            return None

        content_type = response.headers.get("content-type", "")
        if "application/pdf" not in content_type and "application/octet-stream" not in content_type:
            logger.warning(
                "arXiv response for %s is not a PDF (content-type: %s)", url, content_type
            )
            return None

        dest.write_bytes(response.content)
        logger.info("Saved arXiv PDF for %s to %s", paper.doi or paper.id, dest)
        return dest
