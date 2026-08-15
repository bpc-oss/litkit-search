"""bioRxiv/medRxiv search source.

Uses Crossref for keyword search because the native bioRxiv Content API only
supports date windows and DOI/detail lookup. DOI resolution still uses the
bioRxiv Content API v1.

API docs: https://www.biorxiv.org/about/content-api
"""

from __future__ import annotations

from contextlib import suppress
from typing import Any

import httpx

from litkit.core.models import Author, Paper, SearchResult, Venue
from litkit.sources import register
from litkit.sources.base import SearchSource

_SERVERS = {"biorxiv", "medrxiv"}


@register
class Biorxiv(SearchSource):
    name = "biorxiv"
    rate_limit_key = "biorxiv"

    def __init__(self, config: Any, client: httpx.AsyncClient | None = None):
        super().__init__(config, client)
        self._base = "https://api.biorxiv.org"
        self._crossref_base = "https://api.crossref.org/works"

    async def search(self, query: str, limit: int = 20, **kwargs: Any) -> SearchResult:
        params: dict[str, Any] = {
            "query.bibliographic": query,
            "filter": "prefix:10.1101,type:posted-content",
            "rows": min(limit, 100),
            "sort": "score",
            "order": "desc",
        }
        if self._config.crossref_email:
            params["mailto"] = self._config.crossref_email

        resp = await self._rate_limited(self._client.get(self._crossref_base, params=params))
        resp.raise_for_status()
        message = resp.json().get("message", {})
        papers = [self._parse_crossref(item) for item in message.get("items", [])]
        return SearchResult(
            papers=tuple(papers),
            total_estimated=message.get("total-results", len(papers)),
            source=self.name,
        )

    async def fetch_by_doi(self, doi: str) -> Paper | None:
        doi_clean = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")
        resp = await self._rate_limited(
            self._client.get(f"{self._base}/details/biorxiv/{doi_clean}")
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        collection = data.get("collection") or []
        if not collection:
            return None
        return self._parse(collection[0])

    def _parse_crossref(self, item: dict[str, Any]) -> Paper:
        doi = (item.get("DOI") or "").replace("https://doi.org/", "")
        title_list = item.get("title") or []
        title = title_list[0] if title_list else ""
        authors = tuple(
            Author(
                given=au.get("given", ""),
                family=au.get("family", ""),
                orcid=(au.get("ORCID", "") or "").replace("https://orcid.org/", ""),
            )
            for au in (item.get("author") or [])
        )

        year = 0
        for date_field in ("posted", "published-online", "issued", "created"):
            date_info = item.get(date_field) or {}
            date_parts = date_info.get("date-parts") or []
            if date_parts and date_parts[0]:
                try:
                    year = int(date_parts[0][0])
                    break
                except (TypeError, ValueError):
                    pass

        source_text = " ".join(
            str(part)
            for part in (
                item.get("publisher") or "",
                " ".join(item.get("container-title") or []),
                " ".join(inst.get("name", "") for inst in item.get("institution") or []),
            )
        ).lower()
        server = "medrxiv" if "medrxiv" in source_text else "biorxiv"
        venue_name = "medRxiv" if server == "medrxiv" else "bioRxiv"
        link_list = item.get("link") or []
        pdf_url = ""
        for link in link_list:
            if "pdf" in (link.get("content-type") or "").lower():
                pdf_url = link.get("URL") or ""
                break

        return Paper(
            doi=doi,
            title=title,
            authors=authors,
            venue=Venue(name=venue_name, short_name=server, type="repository"),
            year=year,
            abstract=item.get("abstract") or "",
            pdf_url=pdf_url,
            source_url=f"https://doi.org/{doi}" if doi else "",
            source=self.name,
            oa_status="green",
            extra={
                "server": server,
                "crossref_type": item.get("type", ""),
            },
        )

    def _parse(self, item: dict[str, Any]) -> Paper:
        doi = (item.get("doi") or "").replace("https://doi.org/", "")
        title = item.get("title") or ""
        date_str = item.get("date") or ""
        year = 0
        if len(date_str) >= 4:
            with suppress(ValueError):
                year = int(date_str[:4])

        authors_data = item.get("authors") or ""
        authors_list: list[Author] = []
        for raw in authors_data.split(";"):
            raw = raw.strip()
            if not raw or "," not in raw:
                if raw:
                    authors_list.append(Author(given="", family=raw))
                continue
            family, given = raw.split(",", 1)
            authors_list.append(Author(given=given.strip(), family=family.strip()))

        server = (item.get("server") or "").lower()
        server = server if server in _SERVERS else "biorxiv"
        venue_name = "bioRxiv" if server == "biorxiv" else "medRxiv"

        return Paper(
            doi=doi,
            title=title,
            authors=tuple(authors_list),
            venue=Venue(name=venue_name, short_name=server, type="repository"),
            year=year,
            source=self.name,
            oa_status="green",
            extra={"server": server},
        )
