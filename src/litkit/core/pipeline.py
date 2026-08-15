"""Orchestration pipeline: search → dedupe → enrich → download.

Coordinates multiple search sources in parallel, deduplicates results,
and optionally downloads PDFs via the download chain.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from litkit.config import EnvConfig, load_env
from litkit.core.cache import MetadataCache
from litkit.core.dedup import merge_duplicates
from litkit.core.models import Paper, SearchResult
from litkit.sources import _registry


class Pipeline:
    """Multi-source search pipeline with caching and optional download."""

    def __init__(
        self,
        config: EnvConfig | None = None,
        cache: MetadataCache | None = None,
    ):
        self._config = config or load_env()
        self._cache = cache or MetadataCache()

    async def search(
        self,
        query: str,
        sources: list[str] | None = None,
        limit: int = 20,
        **kwargs: Any,
    ) -> list[Paper]:
        """Search across *sources*, deduplicate, and return merged results.

        Args:
            query: Search query string.
            sources: Source names to query (None = all registered).
            limit: Approximate max results per source.

        Returns:
            Deduplicated list of Papers sorted by (has_doi desc, citations desc).
        """
        sources = sources or list(_registry)
        source_instances = []
        for name in sources:
            cls = _registry.get(name)
            if cls is None:
                self._cache.audit("unknown_source", f"{query}: {name}")
                continue
            source_instances.append(cls(self._config))
        try:
            # Parallel search across all sources
            results: list[SearchResult] = []
            tasks = [
                asyncio.create_task(src.search(query, limit=limit, **kwargs))
                for src in source_instances
            ]
            for task in asyncio.as_completed(tasks):
                try:
                    result = await task
                    results.append(result)
                except Exception as exc:
                    # Source failure is non-fatal; log via cache
                    self._cache.audit("search_error", f"{query}: {exc}")

            # Flatten and deduplicate
            all_papers = []
            for r in results:
                all_papers.extend(r.papers)
            all_papers = merge_duplicates(all_papers)

            # Cache results
            self._cache.put_papers(all_papers)

            # Sort: papers with DOI first, then by citation count
            all_papers.sort(key=lambda p: (1 if p.doi else 0, p.citations_count), reverse=True)
            return all_papers
        finally:
            for src in source_instances:
                await src.close()

    async def fetch_by_doi(self, doi: str, sources: list[str] | None = None) -> Paper | None:
        """Fetch a single paper by DOI, checking cache first."""
        sources = sources or list(_registry)

        # Check cache first
        cached = self._cache.get_paper(doi)
        found: list[Paper] = []
        if cached is not None:
            found.append(cached)

        for name in sources:
            cls = _registry.get(name)
            if cls is None:
                continue
            src = cls(self._config)
            try:
                paper = await src.fetch_by_doi(doi)
                if paper is not None:
                    found.append(paper)
            except Exception:
                continue
            finally:
                await src.close()
        if not found:
            return None

        merged = merge_duplicates(found)[0]
        self._cache.put_paper(merged)
        return merged

    async def download_pdfs(
        self,
        papers: list[Paper],
        dest_dir: str | Path | None = None,
        max_concurrency: int = 3,
    ) -> dict[str, Path | None]:
        """Download PDFs for a list of papers.

        Returns dict mapping paper.id to local Path or None on failure.
        """
        del dest_dir
        from litkit.downloaders import (
            AnnasArchiveDownloader,
            ArxivDownloader,
            BiorxivDownloader,
            ChineseInstitutionalDownloader,
            DownloadChain,
            EuropePmcDownloader,
            InstitutionalDownloader,
            LibgenDownloader,
            PmcFtpDownloader,
            PublisherDirectDownloader,
            SciHubDownloader,
            UnpaywallDownloader,
        )

        chain = DownloadChain(self._cache, self._config)
        chain.add(ArxivDownloader(self._cache, self._config))
        chain.add(BiorxivDownloader(self._cache, self._config))
        chain.add(UnpaywallDownloader(self._cache, self._config))
        chain.add(EuropePmcDownloader(self._cache, self._config))
        chain.add(PmcFtpDownloader(self._cache, self._config))
        chain.add(PublisherDirectDownloader(self._cache, self._config))
        chain.add(SciHubDownloader(self._cache, self._config))
        chain.add(LibgenDownloader(self._cache, self._config))
        chain.add(AnnasArchiveDownloader(self._cache, self._config))
        chain.add(ChineseInstitutionalDownloader(self._cache, self._config))
        chain.add(InstitutionalDownloader(self._cache, self._config))

        results: dict[str, Path | None] = {}
        semaphore = asyncio.Semaphore(max(1, max_concurrency))

        async def _download_one(paper: Paper) -> None:
            async with semaphore:
                download_paper = paper
                if paper.doi:
                    enriched = await self.fetch_by_doi(paper.doi)
                    if enriched is not None:
                        download_paper = merge_duplicates([paper, enriched])[0]
                results[paper.id] = await chain.download(download_paper)

        try:
            await asyncio.gather(*[_download_one(paper) for paper in papers])
        finally:
            await chain.close()
        return results
