"""OpenAlex search source — the reference implementation.

Docs: https://docs.openalex.org/
Rate limit: 10 req/s with API key, 1 req/s without (but we always use 10).
"""

from __future__ import annotations

from typing import Any

import httpx

from litkit.core.models import Author, Paper, SearchResult, Venue
from litkit.sources import register
from litkit.sources.base import SearchSource


@register
class OpenAlex(SearchSource):
    name = "openalex"
    rate_limit_key = "openalex"

    def __init__(self, config: Any, client: httpx.AsyncClient | None = None):
        super().__init__(config, client)
        self._base = "https://api.openalex.org"
        self._email_param = ""
        if config.crossref_email:
            self._email_param = f"mailto={config.crossref_email}"

    async def search(self, query: str, limit: int = 20, **kwargs: Any) -> SearchResult:
        params: dict[str, Any] = {
            "search": query,
            "per-page": min(limit, 200),
            "sort": "relevance_score:desc",
        }
        if self._email_param:
            params["mailto"] = self._email_param.replace("mailto=", "")

        filter_parts = []
        if "year_from" in kwargs:
            filter_parts.append(f"from_publication_date:{kwargs['year_from']}-01-01")
        if "year_to" in kwargs:
            filter_parts.append(f"to_publication_date:{kwargs['year_to']}-12-31")
        if filter_parts:
            params["filter"] = ",".join(filter_parts)

        resp = await self._rate_limited(
            self._client.get(
                f"{self._base}/works",
                params=params,
            )
        )
        resp.raise_for_status()
        data = resp.json()

        papers = [self._parse(w) for w in data.get("results", [])]
        return SearchResult(
            papers=tuple(papers),
            total_estimated=data.get("meta", {}).get("count", 0),
            source=self.name,
        )

    async def fetch_by_doi(self, doi: str) -> Paper | None:
        resp = await self._rate_limited(
            self._client.get(
                f"{self._base}/works/doi:{doi}",
            )
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return self._parse(resp.json())

    def _parse(self, w: dict[str, Any]) -> Paper:
        doi = (w.get("doi") or "").replace("https://doi.org/", "")
        authors = tuple(
            Author(
                given=au.get("author", {}).get("given_name", ""),
                family=au.get("author", {}).get("family_name", ""),
                orcid=(au.get("author", {}).get("orcid") or ""),
            )
            for au in (w.get("authorships") or [])
        )
        venue_data = w.get("primary_location", {}) or {}
        source = venue_data.get("source") or {}
        venue = Venue(
            name=(source.get("display_name") or ""),
            short_name=(source.get("shortened_display_name") or ""),
            issn=((source.get("issn_l") or "") or (source.get("issn") or [""])[0]),
            publisher=(source.get("host_organization_name") or ""),
            type=(source.get("type") or ""),
        )
        loc = w.get("open_access") or {}
        subjects = tuple(
            c.get("display_name", "") for c in (w.get("concepts") or []) if c.get("score", 0) > 50
        )
        extra: dict[str, Any] = {}
        if w.get("is_retracted"):
            extra["is_retracted"] = True
            extra["retraction_notice"] = w.get("retraction_notice") or ""

        return Paper(
            doi=doi,
            title=(w.get("title") or ""),
            authors=authors,
            venue=venue,
            year=(w.get("publication_year") or 0),
            volume=(w.get("biblio") or {}).get("volume", ""),
            issue=(w.get("biblio") or {}).get("issue", ""),
            pages=(w.get("biblio") or {}).get("pages", ""),
            abstract=self._abstract(w),
            citations_count=(w.get("cited_by_count") or 0),
            references_count=len(w.get("referenced_works") or []),
            pdf_url=(loc.get("oa_url") or ""),
            source_url=(w.get("id") or ""),
            source=self.name,
            oa_status=(loc.get("status") or ""),
            license=(loc.get("license") or ""),
            subjects=subjects,
            extra=extra,
        )

    @staticmethod
    def _abstract(w: dict[str, Any]) -> str:
        inv = w.get("abstract_inverted_index")
        if not inv:
            return ""
        word_positions = []
        for word, positions in inv.items():
            for pos in positions:
                word_positions.append((pos, word))
        word_positions.sort()
        return " ".join(w for _, w in word_positions)
