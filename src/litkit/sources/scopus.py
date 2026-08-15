"""Scopus search source (Elsevier API).

Requires SCOPUS_API_KEY in .env.
API docs: https://dev.elsevier.com/api_docs.html
"""

from __future__ import annotations

from typing import Any

import httpx

from litkit.core.models import Author, Paper, SearchResult, Venue
from litkit.sources import register
from litkit.sources.base import SearchSource


@register
class Scopus(SearchSource):
    name = "scopus"
    rate_limit_key = "scopus"

    def __init__(self, config: Any, client: httpx.AsyncClient | None = None):
        super().__init__(config, client)
        self._base = "https://api.elsevier.com/content"
        self._api_key = config.scopus_key

    async def search(self, query: str, limit: int = 20, **kwargs: Any) -> SearchResult:
        if not self._api_key:
            return SearchResult(source=self.name)

        params = {
            "query": query,
            "count": min(limit, 200),
            "start": 0,
            "apiKey": self._api_key,
            "httpAccept": "application/json",
        }
        resp = await self._rate_limited(
            self._client.get(f"{self._base}/search/scopus", params=params)
        )
        resp.raise_for_status()
        data = resp.json()
        entries = data.get("search-results", {}).get("entry", [])
        total = int(data.get("search-results", {}).get("opensearch:totalResults", 0))

        papers = [self._parse(e) for e in entries]
        return SearchResult(papers=tuple(papers), total_estimated=total, source=self.name)

    async def fetch_by_doi(self, doi: str) -> Paper | None:
        if not self._api_key:
            return None
        params = {"apiKey": self._api_key, "httpAccept": "application/json"}
        resp = await self._rate_limited(
            self._client.get(
                f"{self._base}/search/scopus", params={**params, "query": f"DOI({doi})"}
            )
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        entries = data.get("search-results", {}).get("entry", [])
        if not entries:
            return None
        return self._parse(entries[0])

    def _parse(self, e: dict[str, Any]) -> Paper:
        authors_list = []
        for au in e.get("author", []):
            given = ""
            family = au.get("authname", au.get("ce:indexed-name", ""))
            if "," in family:
                parts = family.split(",", 1)
                family = parts[0].strip()
                given = parts[1].strip()
            authors_list.append(Author(given=given, family=family, orcid=(au.get("orcid") or "")))

        venue = Venue(
            name=(e.get("prism:publicationName") or ""),
            issn=(e.get("prism:issn") or ""),
            publisher=(e.get("dc:publisher") or ""),
        )

        doi = (e.get("prism:doi") or "").replace("https://doi.org/", "")

        return Paper(
            doi=doi,
            title=(e.get("dc:title") or ""),
            authors=tuple(authors_list),
            venue=venue,
            year=self._int(e.get("prism:coverDate", "")[:4]),
            volume=(e.get("prism:volume") or ""),
            issue=(e.get("prism:issueIdentifier") or ""),
            pages=(e.get("prism:pageRange") or ""),
            citations_count=self._int(e.get("citedby-count")),
            source_url=f"https://doi.org/{doi}",
            source=self.name,
            subjects=(e.get("subtypeDescription", ""),),
            keywords=tuple(
                kw.strip() for kw in (e.get("authkeywords", "") or "").split("|") if kw.strip()
            ),
        )

    @staticmethod
    def _int(v: Any) -> int:
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0
