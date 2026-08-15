"""Zenodo search source.

Docs: https://developers.zenodo.org/
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from litkit.core.models import Author, Paper, SearchResult, Venue
from litkit.sources import register
from litkit.sources.base import SearchSource


@register
class Zenodo(SearchSource):
    name = "zenodo"
    rate_limit_key = "zenodo"

    def __init__(self, config: Any, client: httpx.AsyncClient | None = None):
        super().__init__(config, client)
        self._base = "https://zenodo.org/api/records"

    async def search(self, query: str, limit: int = 20, **kwargs: Any) -> SearchResult:
        params: dict[str, Any] = {
            "q": query,
            "size": min(limit, 100),
            "sort": "bestmatch",
        }
        resp = await self._rate_limited(self._client.get(self._base, params=params))
        resp.raise_for_status()
        data = resp.json()
        hits = data.get("hits", {})
        records = hits.get("hits", [])
        total = hits.get("total", len(records))
        if isinstance(total, dict):
            total = total.get("value", len(records))
        return SearchResult(
            papers=tuple(self._parse(record) for record in records),
            total_estimated=int(total or 0),
            source=self.name,
        )

    async def fetch_by_doi(self, doi: str) -> Paper | None:
        doi_clean = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")
        result = await self.search(f'doi:"{doi_clean}"', limit=1)
        if result.papers:
            return result.papers[0]
        return None

    def _parse(self, record: dict[str, Any]) -> Paper:
        metadata = record.get("metadata") or {}
        doi = (metadata.get("doi") or record.get("doi") or "").replace("https://doi.org/", "")
        title = metadata.get("title") or record.get("title") or ""

        authors = tuple(self._parse_author(c) for c in metadata.get("creators") or [])
        publication_date = metadata.get("publication_date") or ""
        year = _year(publication_date)

        journal = metadata.get("journal") or {}
        venue_name = journal.get("title") or "Zenodo"
        resource_type = metadata.get("resource_type") or {}
        subjects = tuple(k for k in metadata.get("keywords") or [] if isinstance(k, str))
        files = record.get("files") or []
        pdf_url = self._first_download_url(files)

        links = record.get("links") or {}
        source_url = links.get("html") or links.get("self_html") or ""
        if not source_url and record.get("id") is not None:
            source_url = f"https://zenodo.org/records/{record['id']}"

        return Paper(
            doi=doi,
            title=title,
            authors=authors,
            venue=Venue(
                name=venue_name,
                publisher="Zenodo",
                type=resource_type.get("type") or "repository",
            ),
            year=year,
            abstract=_strip_html(metadata.get("description") or ""),
            pdf_url=pdf_url,
            source_url=source_url,
            source=self.name,
            oa_status=metadata.get("access_right") or "",
            license=(metadata.get("license") or {}).get("id") or "",
            subjects=subjects,
            extra={
                "record_id": record.get("id"),
                "resource_type": resource_type,
            },
        )

    def _parse_author(self, creator: dict[str, Any]) -> Author:
        name = creator.get("name") or ""
        if "," in name:
            family, given = name.split(",", 1)
            return Author(given=given.strip(), family=family.strip())
        return Author(given="", family=name.strip())

    def _first_download_url(self, files: list[dict[str, Any]]) -> str:
        if not files:
            return ""
        preferred = None
        for file_info in files:
            key = (file_info.get("key") or "").lower()
            links = file_info.get("links") or {}
            url = links.get("self") or links.get("download") or ""
            if not url:
                continue
            if key.endswith(".pdf"):
                return url
            preferred = preferred or url
        return preferred or ""


def _year(value: str) -> int:
    if len(value) < 4:
        return 0
    try:
        return int(value[:4])
    except ValueError:
        return 0


def _strip_html(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value).strip()
