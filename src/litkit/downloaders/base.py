"""Base downloader interface and chain-of-responsibility.

Each concrete downloader implements a strategy for retrieving PDFs from a
specific source.  A :class:`DownloadChain` runs them in registration order
and stops at the first success.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import httpx

from litkit.core.cache import MetadataCache
from litkit.core.models import Paper

logger = logging.getLogger(__name__)


class Downloader(ABC):
    """Abstract PDF downloader.

    Subclasses must set a *name* and implement *can_handle* / *download*.
    """

    name: str = ""

    def __init__(self, cache: MetadataCache, config: Any) -> None:
        self._cache = cache
        self._config = config
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
        )

    # ---- abstract interface ------------------------------------------------

    @abstractmethod
    async def can_handle(self, paper: Paper) -> bool:
        """Return True if this downloader can handle *paper*."""

    @abstractmethod
    async def download(self, paper: Paper) -> Path | None:
        """Download PDF for *paper*, return local path or None."""

    # ---- lifecycle ---------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()


class DownloadChain:
    """Run downloaders in priority order, stop at first success.

    Usage::

        chain = DownloadChain(cache, config)
        chain.add(ArxivDownloader(cache, config))
        chain.add(UnpaywallDownloader(cache, config))
        path = await chain.download(paper)
        await chain.close()
    """

    def __init__(
        self,
        cache: MetadataCache | None = None,
        config: Any | None = None,
    ) -> None:
        from litkit.config import load_env

        self._cache = cache or MetadataCache()
        self._config = config or load_env()
        self._downloaders: list[Downloader] = []

    @classmethod
    def create_default(cls) -> DownloadChain:
        """Create a chain with all standard downloaders in priority order."""
        from litkit.downloaders import (
            AnnasArchiveDownloader,
            ArxivDownloader,
            ChineseInstitutionalDownloader,
            EuropePmcDownloader,
            InstitutionalDownloader,
            PmcFtpDownloader,
            PublisherDirectDownloader,
            SciHubDownloader,
            UnpaywallDownloader,
        )

        chain = cls()
        for dl_cls in (
            ArxivDownloader,
            UnpaywallDownloader,
            EuropePmcDownloader,
            PmcFtpDownloader,
            PublisherDirectDownloader,
            SciHubDownloader,
            AnnasArchiveDownloader,
            ChineseInstitutionalDownloader,
            InstitutionalDownloader,
        ):
            chain.add(dl_cls(chain._cache, chain._config))
        return chain

    def add(self, d: Downloader) -> None:
        """Register a downloader (order matters -- first wins)."""
        self._downloaders.append(d)

    def _ordered_downloaders(self, paper: Paper) -> list[Downloader]:
        """Return downloaders reordered by learned DOI-prefix preferences."""
        preferred = self._cache.preferred_downloaders(paper.doi or "")
        if not preferred:
            return list(self._downloaders)
        positions = {name: index for index, name in enumerate(preferred)}
        return sorted(
            self._downloaders,
            key=lambda d: (positions.get(d.name, len(positions)), self._downloaders.index(d)),
        )

    async def download(
        self,
        paper: Paper,
    ) -> Path | None:
        """Try each registered downloader in order.

        Returns the local path to the cached PDF, or None if every downloader
        failed.
        """
        # Fast path: already cached.
        if self._cache.has_pdf(paper.id):
            logger.info("PDF already cached for %s", paper.id)
            return self._cache.pdf_path(paper.id)

        for d in self._ordered_downloaders(paper):
            if not await d.can_handle(paper):
                logger.debug("Skipped %s for %s (cannot handle)", d.name, paper.doi or paper.id)
                continue

            logger.info("Trying %s for %s", d.name, paper.doi or paper.id)
            try:
                path = await d.download(paper)
            except Exception:
                logger.exception("Downloader %s raised for %s", d.name, paper.doi or paper.id)
                self._cache.record_downloader_outcome(paper.doi or "", d.name, success=False)
                self._cache.audit(
                    "download_fail", f"{paper.doi or paper.id} from {d.name} (exception)"
                )
                continue

            if path is not None and self._cache.is_valid_pdf(path):
                logger.info("Downloaded %s via %s -> %s", paper.doi or paper.id, d.name, path)
                self._cache.record_downloader_outcome(paper.doi or "", d.name, success=True)
                self._cache.audit("download_ok", f"{paper.doi or paper.id} from {d.name}")
                return path

            if path is not None and path == self._cache.pdf_path(paper.id):
                path.unlink(missing_ok=True)

            self._cache.record_downloader_outcome(paper.doi or "", d.name, success=False)
            self._cache.audit("download_fail", f"{paper.doi or paper.id} from {d.name}")

        return None

    async def close(self) -> None:
        """Close every registered downloader."""
        for d in self._downloaders:
            await d.close()
