"""CORE API â€” 250M+ OA papers from institutional repositories.

Free tier: https://core.ac.uk/services/api/
"""

from __future__ import annotations

from typing import Any

import httpx

from litkit.core.models import Author, Paper, SearchResult, Venue
from litkit.sources import register
from litkit.sources.base import SearchSource


@register
class CORE(SearchSource):
    name = "core"
    rate_limit_key = "core"

    def __init__(self, config: Any, client: httpx.AsyncClient | None = None):
        super().__init__(config, client)
        self._base = "https://api.core.ac.uk/v3"
        self._api_key = getattr(config, "core_api_key", "")

    async def search(self, query: str, limit: int = 20, **kwargs: Any) -> SearchResult:
        if not self._api_key:
            return SearchResult(source=self.name)

        headers = {"Authorization": f"Bearer {self._api_key}"}
        params = {
            "q": query,
            "limit": min(limit, 100),
            "offset": 0,
        }
        resp = await self._rate_limited(
            self._client.get(f"{self._base}/search/outputs", params=params, headers=headers)
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        total = data.get("total", 0)

        papers = [self._parse(r) for r in results]
        return SearchResult(papers=tuple(papers), total_estimated=total, source=self.name)

    async def fetch_by_doi(self, doi: str) -> Paper | None:
        if not self._api_key:
            return None
        headers = {"Authorization": f"Bearer {self._api_key}"}
        resp = await self._rate_limited(
            self._client.get(
                f"{self._base}/search/outputs",
                params={"q": f'doi:"{doi}"', "limit": 1},
                headers=headers,
            )
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if not results:
            return None
        return self._parse(results[0])

    def _parse(self, r: dict[str, Any]) -> Paper:
        authors_list = []
        for name in r.get("authors", []):
            authors_list.append(Author(family=name))

        doi = (r.get("doi") or "").replace("https://doi.org/", "")
        full_text = r.get("fullText", "")
        abstract = r.get("abstract", "") or full_text[:500] if full_text else ""

        return Paper(
            doi=doi,
            title=(r.get("title") or ""),
            authors=tuple(authors_list),
            venue=Venue(name=(r.get("journalName") or "")),
            year=(r.get("yearPublished") or 0),
            volume=(r.get("volume") or ""),
            issue=(r.get("issue") or ""),
            pages=(r.get("pages") or ""),
            abstract=abstract,
            citations_count=int(r.get("citationCount", 0)),
            pdf_url=(r.get("downloadUrl") or r.get("fullTextIdentifier", "")),
            source_url=(r.get("sourceUrl") or ""),
            source=self.name,
            oa_status="gold",
            subjects=tuple(r.get("subjects", [])),
            keywords=tuple(r.get("keywords", [])),
        )

