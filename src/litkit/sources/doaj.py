"""DOAJ (Directory of Open Access Journals) search source.

API: https://doaj.org/api/v3/docs
"""

from __future__ import annotations

from typing import Any

import httpx

from litkit.core.models import Author, Paper, SearchResult, Venue
from litkit.sources import register
from litkit.sources.base import SearchSource


@register
class DOAJ(SearchSource):
    name = "doaj"
    rate_limit_key = "openalex"

    def __init__(self, config: Any, client: httpx.AsyncClient | None = None):
        super().__init__(config, client)
        self._base = "https://doaj.org/api/v3"

    async def search(self, query: str, limit: int = 20, **kwargs: Any) -> SearchResult:
        params = {
            "query": query,
            "page": 1,
            "pageSize": min(limit, 100),
            "sort": "score",
        }
        resp = await self._rate_limited(
            self._client.get(f"{self._base}/search/articles/{query}", params=params)
        )
        if resp.status_code != 200:
            return SearchResult(papers=(), total_estimated=0, source=self.name)
        data = resp.json()
        results = data.get("results", [])
        total = data.get("total", 0)

        papers = [self._parse(r) for r in results]
        return SearchResult(papers=tuple(papers), total_estimated=total, source=self.name)

    async def fetch_by_doi(self, doi: str) -> Paper | None:
        resp = await self._rate_limited(self._client.get(f"{self._base}/search/articles/doi:{doi}"))
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        if not results:
            return None
        return self._parse(results[0])

    def _parse(self, r: dict[str, Any]) -> Paper:
        bib = r.get("bibjson", {})
        authors_list = []
        for au in bib.get("author", []):
            name = au.get("name", "")
            given, family = "", name
            if "," in name:
                family, given = name.split(",", 1)
                family, given = family.strip(), given.strip()
            authors_list.append(Author(given=given, family=family))

        venue = Venue(
            name=(bib.get("journal", {}).get("title", "") or ""),
            issn=(bib.get("journal", {}).get("issn", "") or ""),
            publisher=(bib.get("journal", {}).get("publisher", "") or ""),
        )

        doi = ""
        for ident in bib.get("identifier", []):
            if ident.get("type") == "DOI":
                doi = ident.get("id", "").replace("https://doi.org/", "")
                break

        return Paper(
            doi=doi,
            title=(bib.get("title") or ""),
            authors=tuple(authors_list),
            venue=venue,
            year=(bib.get("year") or 0),
            volume=(bib.get("journal", {}).get("volume", "") or ""),
            issue=(bib.get("journal", {}).get("number", "") or ""),
            pages=(bib.get("journal", {}).get("pages", "") or ""),
            abstract=(bib.get("abstract") or ""),
            keywords=tuple(bib.get("keywords", [])),
            source=self.name,
            oa_status="gold",
            subjects=(bib.get("journal", {}).get("country", ""),),
        )
