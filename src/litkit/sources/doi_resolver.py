"""DOI Content Negotiation source.

Fetches metadata from doi.org using HTTP content negotiation (CSL-JSON).
No API key required — uses standard Accept header negotiation.
Only fetch_by_doi is supported; search always returns empty results.
"""

from __future__ import annotations

from typing import Any

import httpx

from litkit.core.models import Author, Paper, SearchResult, Venue
from litkit.sources import register
from litkit.sources.base import SearchSource


@register
class DoiResolver(SearchSource):
    name = "doi_resolver"
    rate_limit_key = "crossref"  # Share rate limit bucket with Crossref

    def __init__(self, config: Any, client: httpx.AsyncClient | None = None):
        super().__init__(config, client)
        self._base = "https://doi.org"

    async def search(self, query: str, limit: int = 20, **kwargs: Any) -> SearchResult:
        return SearchResult(source=self.name)

    async def fetch_by_doi(self, doi: str) -> Paper | None:
        doi_clean = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")
        headers = {"Accept": "application/vnd.citationstyles.csl+json"}
        resp = await self._rate_limited(
            self._client.get(f"{self._base}/{doi_clean}", headers=headers)
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        return self._parse(data)

    def _parse(self, item: dict[str, Any]) -> Paper:
        doi = (item.get("DOI") or "").replace("https://doi.org/", "")

        # CSL-JSON title is a string (unlike Crossref API which wraps in a list)
        title = item.get("title", "")

        # Authors — CSL-JSON uses given/family or literal
        authors = tuple(
            Author(
                given=au.get("given", ""),
                family=au.get("family", ""),
            )
            for au in (item.get("author") or [])
        )

        # Venue — container-title is the journal/book name
        container = item.get("container-title") or ""
        if isinstance(container, list):
            container = container[0] if container else ""
        venue = Venue(
            name=container,
            publisher=item.get("publisher", ""),
            type=item.get("type", ""),
        )

        # Year from issued.date-parts
        year = 0
        issued = item.get("issued") or {}
        date_parts = issued.get("date-parts") or []
        if date_parts and date_parts[0]:
            candidate = date_parts[0][0]
            if candidate:
                year = int(candidate)

        # Keywords — comma-separated string in standard CSL-JSON
        raw_keywords = item.get("keyword", "")
        if isinstance(raw_keywords, str):
            keywords = tuple(k.strip() for k in raw_keywords.split(",") if k.strip())
        elif isinstance(raw_keywords, list):
            keywords = tuple(raw_keywords)
        else:
            keywords = ()

        return Paper(
            doi=doi,
            title=title,
            authors=authors,
            venue=venue,
            year=year,
            volume=item.get("volume", ""),
            issue=item.get("issue", ""),
            pages=item.get("page", ""),
            abstract=item.get("abstract", ""),
            keywords=keywords,
            source_url=f"https://doi.org/{doi}" if doi else "",
            source=self.name,
        )
