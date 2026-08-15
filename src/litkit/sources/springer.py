"""Springer Nature search source.

Requires SPRINGER_API_KEY in .env.
API docs: https://dev.springernature.com/
"""

from __future__ import annotations

from typing import Any

import httpx

from litkit.core.models import Author, Paper, SearchResult, Venue
from litkit.sources import register
from litkit.sources.base import SearchSource


@register
class Springer(SearchSource):
    name = "springer"
    rate_limit_key = "springer"

    def __init__(self, config: Any, client: httpx.AsyncClient | None = None):
        super().__init__(config, client)
        self._base = "https://api.springernature.com/metadata/json"
        self._api_key = getattr(config, "springer_key", "")

    async def search(self, query: str, limit: int = 20, **kwargs: Any) -> SearchResult:
        if not self._api_key:
            return SearchResult(source=self.name)

        params: dict[str, Any] = {
            "q": query,
            "s": 1,
            "p": min(limit, 100),
            "api_key": self._api_key,
        }
        resp = await self._rate_limited(self._client.get(self._base, params=params))
        if resp.status_code != 200:
            return SearchResult(papers=(), total_estimated=0, source=self.name)

        data = resp.json()
        records = data.get("records", [])
        total = 0
        result_info = data.get("result", {})
        if result_info:
            try:
                total = int(result_info.get("total", 0))
            except (TypeError, ValueError):
                total = 0

        papers = [self._parse(r) for r in records]
        return SearchResult(
            papers=tuple(papers),
            total_estimated=total,
            source=self.name,
        )

    async def fetch_by_doi(self, doi: str) -> Paper | None:
        if not self._api_key:
            return None
        params = {"api_key": self._api_key}
        resp = await self._rate_limited(self._client.get(f"{self._base}/doi/{doi}", params=params))
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            return None
        data = resp.json()
        records = data.get("records", [])
        if not records:
            return None
        return self._parse(records[0])

    def _parse(self, record: dict[str, Any]) -> Paper:
        # Authors — creators is an array of {creator: "Doe, John"}
        creators = record.get("creators") or []
        authors = tuple(
            self._parse_creator(c.get("creator", "")) for c in creators if c.get("creator")
        )

        venue = Venue(
            name=(record.get("publicationName") or ""),
            publisher=(record.get("publisher") or ""),
        )

        doi = (record.get("doi") or "").replace("https://doi.org/", "")

        # Year from publicationDate string like "2023-01-15"
        pub_date = record.get("publicationDate") or ""
        year = 0
        if pub_date and len(pub_date) >= 4:
            try:
                year = int(pub_date[:4])
            except (TypeError, ValueError):
                year = 0

        # Pages
        start_page = record.get("startingPage") or ""
        end_page = record.get("endingPage") or ""
        pages = ""
        if start_page and end_page:
            pages = f"{start_page}-{end_page}"
        elif start_page:
            pages = start_page

        # Keywords — comma-separated string
        keywords_raw = record.get("keyword") or ""
        keywords = tuple(kw.strip() for kw in keywords_raw.split(",") if kw.strip())

        # Source URL
        source_url = record.get("url") or ""

        return Paper(
            doi=doi,
            title=(record.get("title") or ""),
            authors=authors,
            venue=venue,
            year=year,
            volume=(record.get("volume") or ""),
            issue=(record.get("number") or ""),
            pages=pages,
            abstract=(record.get("abstract") or ""),
            keywords=keywords,
            source_url=source_url,
            source=self.name,
            oa_status="gold" if record.get("openaccess") else "",
            extra={
                "genre": record.get("genre", ""),
            },
        )

    @staticmethod
    def _parse_creator(creator: str) -> Author:
        """Parse a creator string like "Doe, John" into given/family."""
        if "," in creator:
            parts = creator.split(",", 1)
            family = parts[0].strip()
            given = parts[1].strip()
        else:
            family = creator.strip()
            given = ""
        return Author(given=given, family=family)
