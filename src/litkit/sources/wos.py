"""Web of Science search source (Clarivate API).

Requires WOS_API_KEY in .env.
Uses the WoS Starter API (lite tier).
"""

from __future__ import annotations

from typing import Any

import httpx

from litkit.core.models import Author, Paper, SearchResult, Venue
from litkit.sources import register
from litkit.sources.base import SearchSource


@register
class Wos(SearchSource):
    name = "wos"
    rate_limit_key = "wos"

    def __init__(self, config: Any, client: httpx.AsyncClient | None = None):
        super().__init__(config, client)
        self._base = "https://api.clarivate.com/apis/wos-starter/v1"
        self._api_key = config.wos_key

    async def search(self, query: str, limit: int = 20, **kwargs: Any) -> SearchResult:
        if not self._api_key:
            return SearchResult(source=self.name)

        params = {
            "q": query,
            "limit": min(limit, 50),
            "page": 1,
        }
        headers = {"X-ApiKey": self._api_key, "Accept": "application/json"}
        resp = await self._rate_limited(
            self._client.get(f"{self._base}/documents", params=params, headers=headers)
        )
        if resp.status_code == 403:
            return SearchResult(source=self.name)
        resp.raise_for_status()
        data = resp.json()
        hits = data.get("hits", [])
        total = data.get("metadata", {}).get("total", 0)

        papers = [self._parse(h) for h in hits]
        return SearchResult(papers=tuple(papers), total_estimated=total, source=self.name)

    async def fetch_by_doi(self, doi: str) -> Paper | None:
        if not self._api_key:
            return None
        headers = {"X-ApiKey": self._api_key, "Accept": "application/json"}
        resp = await self._rate_limited(
            self._client.get(
                f"{self._base}/documents",
                params={"q": f'DO="{doi}"', "limit": 1},
                headers=headers,
            )
        )
        if resp.status_code == 404 or resp.status_code == 403:
            return None
        resp.raise_for_status()
        hits = resp.json().get("hits", [])
        if not hits:
            return None
        return self._parse(hits[0])

    def _parse(self, h: dict[str, Any]) -> Paper:
        authors_list = []
        names = h.get("names", {})
        for au in names.get("authors", []):
            name = au.get("displayName", "")
            given, family = "", name
            if "," in name:
                family, given = name.split(",", 1)
                family, given = family.strip(), given.strip()
            authors_list.append(Author(given=given, family=family))

        src = h.get("source", {})
        venue = Venue(
            name=(src.get("sourceTitle") or ""),
            issn=((h.get("identifiers", {}) or {}).get("issn") or ""),
            publisher="",
        )

        ids = h.get("identifiers", {}) or {}
        doi = (ids.get("doi") or "").replace("https://doi.org/", "")

        pages_obj = src.get("pages", {}) or {}
        pages_str = pages_obj.get("range", "") if isinstance(pages_obj, dict) else str(pages_obj)

        citations_total = 0
        for c in h.get("citations", []):
            citations_total += int(c.get("count", 0))

        return Paper(
            doi=doi,
            title=(h.get("title") or ""),
            authors=tuple(authors_list),
            venue=venue,
            year=int(src.get("publishYear", 0) or 0),
            volume=(src.get("volume") or ""),
            issue=(src.get("issue") or ""),
            pages=pages_str,
            citations_count=citations_total,
            source=self.name,
        )
