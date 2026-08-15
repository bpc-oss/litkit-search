"""IEEE Xplore search source.

Uses the official IEEE Xplore REST API.
Docs: https://developer.ieee.org/docs

Search: GET https://api.ieee.org/api/v1/search/articles
Requires an API key (passed as query parameter).
"""

from __future__ import annotations

from typing import Any

import httpx

from litkit.core.models import Author, Paper, SearchResult, Venue
from litkit.sources import register
from litkit.sources.base import SearchSource


@register
class IeeeXplore(SearchSource):
    name = "ieee_xplore"
    rate_limit_key = "ieee_xplore"

    def __init__(self, config: Any, client: httpx.AsyncClient | None = None):
        super().__init__(config, client)
        self._base = "https://api.ieee.org/api/v1/search/articles"
        self._api_key = getattr(config, "ieee_key", "")

    async def search(self, query: str, limit: int = 20, **kwargs: Any) -> SearchResult:
        if not self._api_key:
            return SearchResult(papers=(), total_estimated=0, source=self.name)

        params: dict[str, Any] = {
            "querytext": query,
            "max_records": min(limit, 100),
            "api_key": self._api_key,
        }
        resp = await self._rate_limited(self._client.get(self._base, params=params))
        if resp.status_code != 200:
            return SearchResult(papers=(), total_estimated=0, source=self.name)
        data = resp.json()
        articles = data.get("articles", [])
        papers = [self._parse(article) for article in articles]
        return SearchResult(
            papers=tuple(papers),
            total_estimated=len(articles),
            source=self.name,
        )

    async def fetch_by_doi(self, doi: str) -> Paper | None:
        if not self._api_key:
            return None
        resp = await self._rate_limited(
            self._client.get(
                self._base,
                params={"doi": doi, "api_key": self._api_key},
            )
        )
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            return None
        data = resp.json()
        articles = data.get("articles", [])
        if not articles:
            return None
        return self._parse(articles[0])

    def _parse(self, item: dict[str, Any]) -> Paper:
        doi = (item.get("doi") or "").strip()

        authors = tuple(
            Author(
                given=(au.get("first_name") or "").strip(),
                family=(au.get("last_name") or "").strip(),
            )
            for au in (item.get("authors") or [])
        )

        year_raw = item.get("publication_year") or 0
        try:
            year = int(year_raw)
        except (ValueError, TypeError):
            year = 0

        venue = Venue(
            name=(item.get("publication_title") or "").strip(),
            publisher=(item.get("publisher") or "").strip(),
            type="journal",
        )

        extra: dict[str, Any] = {}
        article_number = item.get("article_number") or ""
        if article_number:
            extra["article_number"] = str(article_number).strip()

        return Paper(
            doi=doi,
            title=(item.get("title") or "").strip(),
            authors=authors,
            venue=venue,
            year=year,
            volume=(item.get("volume") or "").strip(),
            issue=(item.get("issue") or "").strip(),
            pages=(item.get("pages") or "").strip(),
            abstract=(item.get("abstract") or "").strip(),
            source_url=f"https://doi.org/{doi}" if doi else "",
            source=self.name,
            oa_status="unknown",
            extra=extra,
        )
