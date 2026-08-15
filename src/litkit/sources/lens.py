"""Lens.org â€” scholarly search + patent data.

API: https://docs.lens.org/
Requires LENS_API_KEY in .env (free tier available).
"""

from __future__ import annotations

from typing import Any

import httpx

from litkit.core.models import Author, Paper, SearchResult, Venue
from litkit.sources import register
from litkit.sources.base import SearchSource


@register
class Lens(SearchSource):
    name = "lens"
    rate_limit_key = "openalex"

    def __init__(self, config: Any, client: httpx.AsyncClient | None = None):
        super().__init__(config, client)
        self._base = "https://api.lens.org/api"
        self._api_key = getattr(config, "lens_api_key", "")

    async def search(self, query: str, limit: int = 20, **kwargs: Any) -> SearchResult:
        if not self._api_key:
            return SearchResult(source=self.name)

        headers = {"Authorization": f"Bearer {self._api_key}"}
        body = {
            "query": {"terms": [{"field": "title", "value": query}]},
            "size": min(limit, 200),
        }
        resp = await self._rate_limited(
            self._client.post(f"{self._base}/scholarly/search", json=body, headers=headers)
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("data", [])
        total = data.get("total", 0)

        papers = [self._parse(r) for r in results]
        return SearchResult(papers=tuple(papers), total_estimated=total, source=self.name)

    async def fetch_by_doi(self, doi: str) -> Paper | None:
        if not self._api_key:
            return None
        headers = {"Authorization": f"Bearer {self._api_key}"}
        body = {
            "query": {"terms": [{"field": "doi", "value": doi}]},
            "size": 1,
        }
        resp = await self._rate_limited(
            self._client.post(f"{self._base}/scholarly/search", json=body, headers=headers)
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        results = resp.json().get("data", [])
        if not results:
            return None
        return self._parse(results[0])

    def _parse(self, r: dict[str, Any]) -> Paper:
        authors_list = []
        for au in r.get("authors", []):
            authors_list.append(
                Author(
                    given=(au.get("first_name") or ""),
                    family=(au.get("last_name") or ""),
                )
            )

        doi = (r.get("doi") or "").replace("https://doi.org/", "")

        return Paper(
            doi=doi,
            title=(r.get("title") or ""),
            authors=tuple(authors_list),
            venue=Venue(name=(r.get("source") or r.get("journal_title", ""))),
            year=(r.get("year") or r.get("publication_year", 0) or 0),
            volume=(r.get("volume") or ""),
            issue=(r.get("issue") or ""),
            pages=(r.get("pages") or ""),
            abstract=(r.get("abstract") or ""),
            citations_count=int(r.get("citation_count", r.get("times_cited", 0))),
            pdf_url=(r.get("open_access_pdf_url") or r.get("pdf_url", "")),
            source=self.name,
            oa_status=(r.get("open_access_status", "")),
        )

