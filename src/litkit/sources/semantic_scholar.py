"""Semantic Scholar search source.

Docs: https://api.semanticscholar.org/api-docs/graph
Rate limit: 10 req/s (with API key), 1 req/s without.
"""

from __future__ import annotations

from typing import Any

import httpx

from litkit.core.models import Author, Paper, SearchResult, Venue
from litkit.sources import register
from litkit.sources.base import SearchSource


@register
class SemanticScholar(SearchSource):
    name = "semantic_scholar"
    rate_limit_key = "semantic_scholar"

    def __init__(self, config: Any, client: httpx.AsyncClient | None = None):
        super().__init__(config, client)
        self._base = "https://api.semanticscholar.org/graph/v1"
        self._fields = (
            "title,authors,venue,year,externalIds,abstract,"
            "citationCount,referenceCount,publicationTypes,openAccessPdf"
        )

    async def search(self, query: str, limit: int = 20, **kwargs: Any) -> SearchResult:
        params: dict[str, Any] = {
            "query": query,
            "limit": min(limit, 100),
            "fields": self._fields,
        }

        resp = await self._rate_limited(
            self._client.get(
                f"{self._base}/paper/search",
                params=params,
            )
        )
        if resp.status_code == 404:
            return SearchResult(papers=(), total_estimated=0, source=self.name)
        resp.raise_for_status()
        data = resp.json()

        papers = [self._parse(p) for p in (data.get("data") or [])]
        return SearchResult(
            papers=tuple(papers),
            total_estimated=data.get("total", 0),
            source=self.name,
        )

    async def fetch_by_doi(self, doi: str) -> Paper | None:
        doi_clean = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")
        resp = await self._rate_limited(
            self._client.get(
                f"{self._base}/paper/DOI:{doi_clean}",
                params={"fields": self._fields},
            )
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return self._parse(resp.json())

    def _parse(self, p: dict[str, Any]) -> Paper:
        external_ids = p.get("externalIds") or {}
        doi = (external_ids.get("DOI") or "").replace("https://doi.org/", "")

        # Authors: S2 returns {name, authorId} â€” parse the name string
        authors_data = p.get("authors") or []
        authors = tuple(
            Author(
                given=self._parse_given_name(au.get("name", "")),
                family=self._parse_family_name(au.get("name", "")),
            )
            for au in authors_data
        )

        # Venue
        venue_name = p.get("venue") or ""
        venue = Venue(name=venue_name, type="")

        # Type-based OA status from publicationTypes
        pub_types = p.get("publicationTypes") or []
        oa_status = self._determine_oa(pub_types)

        # openAccessPdf
        pdf_info = p.get("openAccessPdf") or {}
        pdf_url = pdf_info.get("url") or ""
        if pdf_url and not pdf_url.startswith("http"):
            pdf_url = ""

        # Subjects from publication types
        subjects = tuple(str(t) for t in pub_types)

        return Paper(
            doi=doi,
            title=(p.get("title") or ""),
            authors=authors,
            venue=venue,
            year=(p.get("year") or 0),
            abstract=(p.get("abstract") or ""),
            citations_count=(p.get("citationCount") or 0),
            references_count=(p.get("referenceCount") or 0),
            pdf_url=pdf_url,
            source_url=(
                f"https://www.semanticscholar.org/paper/{p.get('paperId', '')}"
                if p.get("paperId")
                else ""
            ),
            source=self.name,
            oa_status=oa_status,
            subjects=subjects,
            extra={
                "publication_types": pub_types,
                "s2_paper_id": p.get("paperId", ""),
                "s2_corpus_id": external_ids.get("CorpusId", ""),
            },
        )

    @staticmethod
    def _parse_given_name(name: str) -> str:
        """Extract given (first) name from a full name string."""
        if not name:
            return ""
        parts = name.strip().split()
        if len(parts) <= 1:
            return name.strip()
        return " ".join(parts[:-1])

    @staticmethod
    def _parse_family_name(name: str) -> str:
        """Extract family (last) name from a full name string."""
        if not name:
            return ""
        parts = name.strip().split()
        if len(parts) <= 1:
            return ""
        return parts[-1]

    @staticmethod
    def _determine_oa(pub_types: list[str]) -> str:
        """Map Semantic Scholar publication types to OA status string."""
        type_map: dict[str, str] = {
            "OpenAccess": "gold",
            "Free": "green",
        }
        for pt in pub_types:
            mapped = type_map.get(pt)
            if mapped:
                return mapped
        return ""
