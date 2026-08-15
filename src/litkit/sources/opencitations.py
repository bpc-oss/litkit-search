"""OpenCitations â€” citation graph data.

Provides citation counts and reference lists via the COCI index.
https://opencitations.net/
"""

from __future__ import annotations

from typing import Any

import httpx

from litkit.core.models import Citation, Paper, SearchResult
from litkit.sources import register
from litkit.sources.base import SearchSource


@register
class OpenCitations(SearchSource):
    name = "opencitations"
    rate_limit_key = "openalex"  # generous rate limit

    def __init__(self, config: Any, client: httpx.AsyncClient | None = None):
        super().__init__(config, client)
        self._base = "https://opencitations.net/index/coci/api/v1"

    async def search(self, query: str, limit: int = 20, **kwargs: Any) -> SearchResult:
        return SearchResult(source=self.name)

    async def fetch_by_doi(self, doi: str) -> Paper | None:
        return None

    async def get_citations(self, doi: str) -> list[Citation]:
        """Get all citations TO *doi*."""
        resp = await self._rate_limited(self._client.get(f"{self._base}/citations/{doi}"))
        if resp.status_code != 200:
            return []
        data = resp.json()
        return [
            Citation(
                citing_id=c.get("citing", ""),
                cited_id=c.get("cited", ""),
                doi=c.get("cited", ""),
            )
            for c in data
        ]

    async def get_references(self, doi: str) -> list[Citation]:
        """Get all references FROM *doi*."""
        resp = await self._rate_limited(self._client.get(f"{self._base}/references/{doi}"))
        if resp.status_code != 200:
            return []
        data = resp.json()
        return [
            Citation(
                citing_id=c.get("citing", ""),
                cited_id=c.get("cited", ""),
                doi=c.get("citing", ""),
            )
            for c in data
        ]
