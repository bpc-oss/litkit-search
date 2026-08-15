"""BASE (Bielefeld Academic Search Engine) â€” 240M+ documents.

API: https://api.base-search.net/
Open access, no key required (polite use).
"""

from __future__ import annotations

from typing import Any

import httpx

from litkit.core.models import Author, Paper, SearchResult, Venue
from litkit.sources import register
from litkit.sources.base import SearchSource


@register
class BASE(SearchSource):
    name = "base"
    rate_limit_key = "openalex"

    def __init__(self, config: Any, client: httpx.AsyncClient | None = None):
        super().__init__(config, client)
        self._base = "https://api.base-search.net/v1"

    async def search(self, query: str, limit: int = 20, **kwargs: Any) -> SearchResult:
        params = {
            "query": query,
            "size": min(limit, 100),
            "from": 0,
        }
        resp = await self._rate_limited(self._client.get(f"{self._base}/search", params=params))
        resp.raise_for_status()
        data = resp.json()
        docs = data.get("response", {}).get("docs", [])
        total = data.get("response", {}).get("numFound", 0)

        papers = [self._parse(d) for d in docs]
        return SearchResult(papers=tuple(papers), total_estimated=total, source=self.name)

    async def fetch_by_doi(self, doi: str) -> Paper | None:
        resp = await self._rate_limited(
            self._client.get(
                f"{self._base}/search",
                params={"query": f"doi:{doi}", "size": 1},
            )
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        docs = resp.json().get("response", {}).get("docs", [])
        if not docs:
            return None
        return self._parse(docs[0])

    def _parse(self, d: dict[str, Any]) -> Paper:
        authors_list = [
            Author(family=a) if isinstance(a, str) else Author(family=a.get("name", ""))
            for a in (d.get("author", []) or [])
        ]

        doi = ""
        for link in d.get("link", []):
            if "doi.org" in str(link):
                full = link if isinstance(link, str) else link.get("href", "")
                doi = full.replace("https://doi.org/", "").replace("http://doi.org/", "")
                break

        return Paper(
            doi=doi,
            title=(
                d.get("title", [""])[0] if isinstance(d.get("title"), list) else d.get("title", "")
            ),
            authors=tuple(authors_list),
            venue=Venue(name=(d.get("source", ""))),
            year=int(d.get("year", 0)) if d.get("year") else 0,
            abstract=(
                d.get("abstract", [""])[0]
                if isinstance(d.get("abstract"), list)
                else d.get("abstract", "")
            ),
            source=self.name,
            subjects=tuple(d.get("dcsubject", [])),
        )

