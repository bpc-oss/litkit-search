"""scite.ai search source — citation context analysis.

API: https://api.scite.ai/api/v1
Requires SCITE_API_KEY in .env.
Rate limit: 5 req/s.

This source is primarily a citation context analysis tool. The standard
search method is not its primary use case; fetch_by_doi provides paper
metadata along with citation statements (contexts).
"""

from __future__ import annotations

from typing import Any

import httpx

from litkit.core.models import Author, Paper, SearchResult
from litkit.sources import register
from litkit.sources.base import SearchSource


@register
class SciteSource(SearchSource):
    name = "scite"
    rate_limit_key = "scite"

    def __init__(self, config: Any, client: httpx.AsyncClient | None = None):
        super().__init__(config, client)
        self._base = "https://api.scite.ai/api/v1"
        self._api_key = getattr(config, "scite_key", "")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
        }

    async def search(self, query: str, limit: int = 20, **kwargs: Any) -> SearchResult:
        """Search scite.ai by keyword.

        scite.ai is not a general-purpose search engine. This is a stub
        that returns an empty SearchResult.
        """
        return SearchResult(source=self.name)

    async def fetch_by_doi(self, doi: str) -> Paper | None:
        """Fetch a single paper by DOI, including citation contexts.

        GET /papers?doi={doi}

        Returns None if the DOI is not found or no API key is configured.
        Citation contexts are stored in extra["scite_contexts"].
        """
        if not self._api_key:
            return None

        resp = await self._rate_limited(
            self._client.get(
                f"{self._base}/papers",
                params={"doi": doi},
                headers=self._headers(),
            )
        )
        if resp.status_code == 404:
            return None
        if resp.status_code == 422:
            # scite returns 422 for DOIs it cannot find
            return None
        resp.raise_for_status()
        data = resp.json()

        if not data or not isinstance(data, list) or len(data) == 0:
            return None

        return self._parse(data[0], doi)

    def _parse(self, data: dict[str, Any], doi: str) -> Paper:
        """Parse a scite API response into a Paper."""
        title = data.get("title", "")
        year = data.get("year", 0)
        if isinstance(year, str) and year.isdigit():
            year = int(year)
        elif not isinstance(year, int):
            year = 0

        journal = data.get("journal", "")

        # Authors come as strings like "Doe, John" or "Doe J"
        authors_list: list[Author] = []
        for name in data.get("authors", []):
            if isinstance(name, str):
                authors_list.append(self._parse_author(name))

        cited_by = data.get("cited_by", 0)
        reference_count = data.get("reference_count", 0)
        url = data.get("url", "")

        # Citation statements
        contexts: list[dict[str, Any]] = []
        citation_statements = data.get("citation_statements", [])
        for stmt in citation_statements:
            ctx = {
                "citing_title": stmt.get("citing_title", ""),
                "text": stmt.get("text", ""),
            }
            contexts.append(ctx)

        extra: dict[str, Any] = {}
        if contexts:
            extra["scite_contexts"] = contexts

        return Paper(
            doi=doi,
            title=title,
            authors=tuple(authors_list),
            venue=self._make_venue(journal),
            year=year,
            citations_count=int(cited_by) if cited_by else 0,
            references_count=int(reference_count) if reference_count else 0,
            source_url=url,
            source=self.name,
            extra=extra,
        )

    @staticmethod
    def _parse_author(name: str) -> Author:
        """Parse an author name string into an Author.

        Handles "Doe, John" and "Doe J" formats.
        """
        if "," in name:
            parts = name.split(",", 1)
            family = parts[0].strip()
            given = parts[1].strip()
        else:
            parts = name.strip().rsplit(" ", 1)
            if len(parts) == 2:
                given = parts[0].strip()
                family = parts[1].strip()
            else:
                family = parts[0].strip()
                given = ""
        return Author(given=given, family=family)

    @staticmethod
    def _make_venue(name: str) -> Any:
        """Create a Venue for scite results."""
        from litkit.core.models import Venue

        return Venue(name=name)
