"""Crossref search source.

Docs: https://api.crossref.org/swagger-ui/index.html
Rate limit: 50 req/s (with polite mailto parameter).
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from litkit.core.models import Author, Paper, SearchResult, Venue
from litkit.sources import register
from litkit.sources.base import SearchSource


@register
class Crossref(SearchSource):
    name = "crossref"
    rate_limit_key = "crossref"

    def __init__(self, config: Any, client: httpx.AsyncClient | None = None):
        super().__init__(config, client)
        self._base = "https://api.crossref.org/works"

    async def search(self, query: str, limit: int = 20, **kwargs: Any) -> SearchResult:
        params: dict[str, Any] = {
            "query": query,
            "rows": min(limit, 1000),
        }
        if self._config.crossref_email:
            params["mailto"] = self._config.crossref_email

        resp = await self._rate_limited(self._client.get(self._base, params=params))
        resp.raise_for_status()
        data = resp.json()
        message = data.get("message", {})
        items = message.get("items", [])

        papers = [self._parse(item) for item in items]
        return SearchResult(
            papers=tuple(papers),
            total_estimated=message.get("total-results", 0),
            source=self.name,
        )

    async def fetch_by_doi(self, doi: str) -> Paper | None:
        doi_clean = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")
        resp = await self._rate_limited(self._client.get(f"{self._base}/{doi_clean}"))
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        message = data.get("message", {})
        return self._parse(message)

    def _parse(self, item: dict[str, Any]) -> Paper:
        # Title comes as a list; take first element
        title_list = item.get("title") or []
        title = title_list[0] if title_list else ""

        # Normalise DOI
        doi = (item.get("DOI") or "").replace("https://doi.org/", "")

        # Authors
        authors = tuple(
            Author(
                given=au.get("given", ""),
                family=au.get("family", ""),
                orcid=(au.get("ORCID", "") or "").replace("https://orcid.org/", ""),
            )
            for au in (item.get("author") or [])
        )

        # Venue from container title
        container = item.get("container-title") or []
        venue_name = container[0] if container else ""
        issn_list = item.get("ISSN") or []
        issn = issn_list[0] if issn_list else ""
        venue = Venue(
            name=venue_name,
            short_name="",
            issn=issn,
            publisher=(item.get("publisher") or ""),
            type=(item.get("type") or ""),
        )

        # Year — try multiple date fields in priority order
        year = 0
        for date_field in ("published-print", "published-online", "issued", "created"):
            date_info = item.get(date_field) or {}
            date_parts = date_info.get("date-parts") or []
            if date_parts and date_parts[0]:
                candidate = date_parts[0][0]
                if candidate:
                    year = int(candidate)
                    break

        # Volume, issue, pages
        volume = item.get("volume") or ""
        issue = item.get("issue") or ""
        pages = item.get("page") or ""

        # Abstract (often JATS HTML-wrapped; strip basic tags)
        abstract = item.get("abstract") or ""
        if abstract:
            abstract = re.sub(r"<[^>]+>", "", abstract)
            abstract = abstract.strip()

        # License
        license_url = ""
        license_list = item.get("license") or []
        if license_list:
            license_url = license_list[0].get("URL") or ""

        # Subjects — Crossref API returns strings
        subjects = tuple(s for s in (item.get("subject") or []) if isinstance(s, str))

        return Paper(
            doi=doi,
            title=title,
            authors=authors,
            venue=venue,
            year=year,
            volume=volume,
            issue=issue,
            pages=pages,
            abstract=abstract,
            source_url=f"https://doi.org/{doi}" if doi else "",
            source=self.name,
            license=license_url,
            subjects=subjects,
            extra={
                "type": item.get("type", ""),
            },
        )
