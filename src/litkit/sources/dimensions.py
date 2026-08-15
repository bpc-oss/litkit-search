"""Dimensions search source.

API: https://api.dimensions.ai/
Free tier uses POST-based DSL queries.
Rate limit: 5 req/s (polite usage).
"""

from __future__ import annotations

from typing import Any

import httpx

from litkit.core.models import Author, Paper, SearchResult, Venue
from litkit.sources import register
from litkit.sources.base import SearchSource


@register
class Dimensions(SearchSource):
    name = "dimensions"
    rate_limit_key = "dimensions"

    def __init__(self, config: Any, client: httpx.AsyncClient | None = None):
        super().__init__(config, client)
        self._base = "https://api.dimensions.ai/api"
        self._api_key = getattr(config, "dimensions_key", "")

    async def search(self, query: str, limit: int = 20, **kwargs: Any) -> SearchResult:
        if not self._api_key:
            return SearchResult(source=self.name)

        dsl = (
            f"search publications in all for '{query}' "
            f"return publications[basics+extras] limit {limit}"
        )
        items = await self._dsl_query(dsl)
        papers = [self._parse(item) for item in items]
        return SearchResult(
            papers=tuple(papers),
            total_estimated=len(items),
            source=self.name,
        )

    async def fetch_by_doi(self, doi: str) -> Paper | None:
        if not self._api_key:
            return None

        dsl = f'search publications where doi = "{doi}" return publications[basics+extras]'
        items = await self._dsl_query(dsl)
        if not items:
            return None
        return self._parse(items[0])

    async def _dsl_query(self, dsl: str) -> list[dict[str, Any]]:
        """Execute a Dimensions DSL query and return parsed publications."""
        headers = {
            "X-API-Key": self._api_key,
            "Content-Type": "application/json",
        }
        body = {"query": dsl}
        resp = await self._rate_limited(
            self._client.post(f"{self._base}/dsl", json=body, headers=headers)
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json()
        # publications are nested inside results array
        results = data.get("results", [])
        publications: list[dict[str, Any]] = []
        for r in results:
            pubs = r.get("publications", [])
            publications.extend(pubs)
        return publications

    def _parse(self, item: dict[str, Any]) -> Paper:
        doi = (item.get("doi") or "").replace("https://doi.org/", "")

        # Authors
        authors = tuple(
            Author(
                given=au.get("first_name", ""),
                family=au.get("last_name", ""),
                orcid=au.get("orcid", ""),
            )
            for au in (item.get("authors") or [])
        )

        # Venue from nested journal object
        journal = item.get("journal") or {}
        venue = Venue(
            name=journal.get("title", ""),
            publisher=item.get("publisher", ""),
        )

        year = item.get("year") or 0

        # Open access status
        oa_status = "gold" if item.get("open_access") else ""

        # Research fields
        subjects = tuple(item.get("field_hdr", []))

        # Altmetrics citations
        altmetrics = item.get("altmetrics") or {}
        citations_count = altmetrics.get("citations_count", 0)

        # Reference count
        references = item.get("reference_ids") or []
        references_count = len(references)

        return Paper(
            doi=doi,
            title=item.get("title", ""),
            authors=authors,
            venue=venue,
            year=year,
            volume=item.get("volume", ""),
            issue=item.get("issue", ""),
            pages=item.get("pages", ""),
            abstract=item.get("abstract", ""),
            citations_count=citations_count or 0,
            references_count=references_count,
            source_url=f"https://doi.org/{doi}" if doi else "",
            source=self.name,
            oa_status=oa_status,
            subjects=subjects,
        )
