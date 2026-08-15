"""arXiv search source.

Docs: https://info.arxiv.org/help/api/index.html
Rate limit: 3 req/s (conservative; no official rate limit).
"""

from __future__ import annotations

from contextlib import suppress
from typing import Any

import httpx
from lxml import etree

from litkit.core.models import Author, Paper, SearchResult, Venue
from litkit.sources import register
from litkit.sources.base import SearchSource

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}


@register
class Arxiv(SearchSource):
    name = "arxiv"
    rate_limit_key = "arxiv"

    def __init__(self, config: Any, client: httpx.AsyncClient | None = None):
        super().__init__(config, client)
        self._base = "https://export.arxiv.org/api/query"

    async def search(self, query: str, limit: int = 20, **kwargs: Any) -> SearchResult:
        params: dict[str, Any] = {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": min(limit, 100),
        }

        resp = await self._rate_limited(self._client.get(self._base, params=params))
        resp.raise_for_status()
        return self._parse_feed(resp.text)

    async def fetch_by_doi(self, doi: str) -> Paper | None:
        doi_clean = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")
        params: dict[str, Any] = {
            "search_query": f"doi:{doi_clean}",
            "start": 0,
            "max_results": 10,
        }

        resp = await self._rate_limited(self._client.get(self._base, params=params))
        resp.raise_for_status()
        feed = etree.fromstring(resp.text.encode("utf-8"))
        entries = feed.findall("atom:entry", _NS)
        if not entries:
            return None
        return self._parse_entry(entries[0])

    def _parse_feed(self, text: str) -> SearchResult:
        """Parse the Atom feed XML into a SearchResult."""
        feed = etree.fromstring(text.encode("utf-8"))

        total_el = feed.find("opensearch:totalResults", _NS)
        total = int(total_el.text) if total_el is not None else 0

        entries = feed.findall("atom:entry", _NS)
        papers = [self._parse_entry(entry) for entry in entries]
        return SearchResult(
            papers=tuple(papers),
            total_estimated=total,
            source=self.name,
        )

    def _parse_entry(self, entry: Any) -> Paper:
        # Title (may be wrapped with whitespace/newlines in the XML)
        title_el = entry.find("atom:title", _NS)
        title = ""
        if title_el is not None and title_el.text:
            title = " ".join(title_el.text.strip().split())

        # arXiv ID URL (e.g. http://arxiv.org/abs/2101.00001v1)
        id_el = entry.find("atom:id", _NS)
        arxiv_id = id_el.text.strip() if id_el is not None else ""

        # Published date (ISO 8601)
        published_el = entry.find("atom:published", _NS)
        year = 0
        if published_el is not None and published_el.text:
            date_str = published_el.text.strip()
            if len(date_str) >= 4:
                with suppress(ValueError):
                    year = int(date_str[:4])

        # Fallback year from updated
        if not year:
            updated_el = entry.find("atom:updated", _NS)
            if updated_el is not None and updated_el.text:
                date_str = updated_el.text.strip()
                if len(date_str) >= 4:
                    with suppress(ValueError):
                        year = int(date_str[:4])

        # Authors
        author_els = entry.findall("atom:author", _NS)
        authors_list: list[Author] = []
        for au in author_els:
            name_el = au.find("atom:name", _NS)
            if name_el is not None and name_el.text:
                name = name_el.text.strip()
                if name:
                    authors_list.append(
                        Author(
                            given=self._parse_given_name(name),
                            family=self._parse_family_name(name),
                        )
                    )
        authors = tuple(authors_list)

        # Summary / abstract
        summary_el = entry.find("atom:summary", _NS)
        abstract = ""
        if summary_el is not None and summary_el.text:
            abstract = " ".join(summary_el.text.strip().split())

        # DOI from arxiv:doi element
        doi_el = entry.find("arxiv:doi", _NS)
        doi = ""
        if doi_el is not None and doi_el.text:
            doi = doi_el.text.strip().replace("https://doi.org/", "")

        # arXiv primary category as subject
        primary_cat = entry.find("arxiv:primary_category", _NS)
        subjects: tuple[str, ...] = ()
        if primary_cat is not None:
            term = primary_cat.get("term", "")
            if term:
                subjects = (term,)

        # Comment (e.g. "Published in NeurIPS 2023")
        extra: dict[str, Any] = {}
        comment_el = entry.find("arxiv:comment", _NS)
        if comment_el is not None and comment_el.text:
            extra["comment"] = comment_el.text.strip()

        # Venue â€” always arXiv
        venue = Venue(
            name="arXiv",
            short_name="arXiv",
            type="repository",
        )

        return Paper(
            doi=doi,
            title=title,
            authors=authors,
            venue=venue,
            year=year,
            abstract=abstract,
            source_url=arxiv_id,
            source=self.name,
            oa_status="green",
            subjects=subjects,
            extra=extra,
        )

    @staticmethod
    def _parse_given_name(name: str) -> str:
        """Extract given name from a full name string (e.g. 'John M. Doe' -> 'John M.')."""
        if not name:
            return ""
        parts = name.strip().split()
        if len(parts) <= 1:
            return name.strip()
        return " ".join(parts[:-1])

    @staticmethod
    def _parse_family_name(name: str) -> str:
        """Extract family name from a full name string (e.g. 'John M. Doe' -> 'Doe')."""
        if not name:
            return ""
        parts = name.strip().split()
        if len(parts) <= 1:
            return ""
        return parts[-1]
