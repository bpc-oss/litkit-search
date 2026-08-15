"""ChemRxiv search source.

ChemRxiv content is indexed by Crossref (DOIs prefix 10.26434).
This source resolves DOIs via the ChemRxiv API and returns structured
metadata.  Search is delegated to Crossref/OpenAlex.
"""

from __future__ import annotations

from contextlib import suppress
from typing import Any

import httpx

from litkit.core.models import Author, Paper, SearchResult, Venue
from litkit.sources import register
from litkit.sources.base import SearchSource


@register
class Chemrxiv(SearchSource):
    name = "chemrxiv"
    rate_limit_key = "chemrxiv"

    def __init__(self, config: Any, client: httpx.AsyncClient | None = None):
        super().__init__(config, client)
        self._base = "https://chemrxiv.org/engage/chemrxiv/public-api/v1"

    async def search(self, query: str, limit: int = 20, **kwargs: Any) -> SearchResult:
        return SearchResult(papers=(), total_estimated=0, source=self.name)

    async def fetch_by_doi(self, doi: str) -> Paper | None:
        doi_clean = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")
        resp = await self._rate_limited(self._client.get(f"{self._base}/item/doi/{doi_clean}"))
        if resp.status_code != 200:
            return None
        data = resp.json()
        return self._parse(data)

    def _parse(self, item: dict[str, Any]) -> Paper:
        doi = (item.get("doi") or "").replace("https://doi.org/", "")
        title = item.get("title") or ""
        authors_list: list[Author] = []
        for au in item.get("authors") or []:
            given = (au.get("firstName") or "").strip()
            family = (au.get("lastName") or "").strip()
            if given or family:
                authors_list.append(Author(given=given, family=family))

        published_date = item.get("publishedDate") or item.get("submittedDate") or ""
        year = 0
        if published_date and len(published_date) >= 4:
            with suppress(ValueError):
                year = int(published_date[:4])

        return Paper(
            doi=doi,
            title=title,
            authors=tuple(authors_list),
            venue=Venue(name="ChemRxiv", short_name="chemrxiv", type="repository"),
            year=year,
            abstract=(item.get("abstract") or ""),
            source=self.name,
            oa_status="green",
        )
