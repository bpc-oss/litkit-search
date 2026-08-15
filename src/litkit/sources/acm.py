"""ACM Digital Library search source.

Requires ACM_API_KEY in .env.
API docs: https://labs.acm.org/api/
"""

from __future__ import annotations

from typing import Any

import httpx

from litkit.core.models import Author, Paper, SearchResult, Venue
from litkit.sources import register
from litkit.sources.base import SearchSource


@register
class ACM(SearchSource):
    name = "acm"
    rate_limit_key = "acm"

    def __init__(self, config: Any, client: httpx.AsyncClient | None = None):
        super().__init__(config, client)
        self._base = "https://api.acm.org/api/v1"
        self._api_key = getattr(config, "acm_key", "")

    async def search(self, query: str, limit: int = 20, **kwargs: Any) -> SearchResult:
        if not self._api_key:
            return SearchResult(source=self.name)

        params: dict[str, Any] = {
            "q": query,
            "rows": min(limit, 50),
        }
        headers = {"X-API-Key": self._api_key}
        resp = await self._rate_limited(
            self._client.get(f"{self._base}/search/citations", params=params, headers=headers)
        )
        if resp.status_code != 200:
            return SearchResult(papers=(), total_estimated=0, source=self.name)

        data = resp.json()
        payload = data.get("data", {})
        items = payload.get("results", [])
        papers = [self._parse(item) for item in items]
        return SearchResult(
            papers=tuple(papers),
            total_estimated=len(items),
            source=self.name,
        )

    async def fetch_by_doi(self, doi: str) -> Paper | None:
        if not self._api_key:
            return None
        headers = {"X-API-Key": self._api_key}
        resp = await self._rate_limited(
            self._client.get(f"{self._base}/citations/doi/{doi}", headers=headers)
        )
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            return None
        data = resp.json()
        item = data.get("data", {})
        if not item or not item.get("doi"):
            return None
        return self._parse(item)

    def _parse(self, item: dict[str, Any]) -> Paper:
        authors = tuple(
            Author(
                given=au.get("given", ""),
                family=au.get("family", ""),
            )
            for au in (item.get("authors") or [])
        )

        venue = Venue(
            name=(item.get("publication_title") or ""),
            publisher=(item.get("publisher") or ""),
        )

        doi = (item.get("doi") or "").replace("https://doi.org/", "")

        return Paper(
            doi=doi,
            title=(item.get("title") or ""),
            authors=authors,
            venue=venue,
            year=int(item["year"]) if item.get("year") else 0,
            volume=(item.get("volume") or ""),
            issue=(item.get("issue") or ""),
            pages=(item.get("pages") or ""),
            abstract=(item.get("abstract") or ""),
            source_url=f"https://doi.org/{doi}" if doi else "",
            source=self.name,
        )
