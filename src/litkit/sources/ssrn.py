"""SSRN search source.

SSRN (Social Science Research Network, part of Elsevier) doesn't have an
official public API. This module implements search by scraping the SSRN
abstract search interface.

Search: POST https://papers.ssrn.com/sol3/DisplayAbstractSearch.cfm
Individual paper: https://papers.ssrn.com/abstract=NUMBER
"""

from __future__ import annotations

from typing import Any

import httpx
from lxml import html

from litkit.core.models import Author, Paper, SearchResult, Venue
from litkit.sources import register
from litkit.sources.base import SearchSource


@register
class Ssrn(SearchSource):
    name = "ssrn"
    rate_limit_key = "ssrn"

    def __init__(self, config: Any, client: httpx.AsyncClient | None = None):
        super().__init__(config, client)
        self._base = "https://papers.ssrn.com/sol3"

    async def search(self, query: str, limit: int = 20, **kwargs: Any) -> SearchResult:
        form_data: dict[str, Any] = {
            "SEARCHTERM": query,
            "sortOrder": "relevance",
            "andOr": "and",
        }
        try:
            resp = await self._rate_limited(
                self._client.post(
                    f"{self._base}/DisplayAbstractSearch.cfm",
                    data=form_data,
                )
            )
            if resp.status_code != 200:
                return SearchResult(papers=(), total_estimated=0, source=self.name)
            return self._parse_html(resp.text)
        except Exception:
            return SearchResult(papers=(), total_estimated=0, source=self.name)

    async def fetch_by_doi(self, doi: str) -> Paper | None:
        return None

    def _parse_html(self, text: str) -> SearchResult:
        """Parse search results HTML into a SearchResult."""
        try:
            tree = html.fromstring(text)
        except Exception:
            return SearchResult(papers=(), total_estimated=0, source=self.name)

        papers: list[Paper] = []

        # SSRN search results contain links to /abstract=NUMBER
        for link in tree.xpath("//a[contains(@href, '/abstract=')]"):
            title = link.text_content().strip()
            if not title:
                continue

            href = link.get("href", "")
            abstract_id = href.split("=")[-1] if "=" in href else ""
            source_url = f"https://papers.ssrn.com/abstract={abstract_id}" if abstract_id else ""

            # Find the containing cell for author / abstract extraction
            cells = link.xpath("./ancestor::td")
            cell = cells[0] if cells else None

            # Authors --- look for <i> elements in the same cell
            author_str = ""
            if cell is not None:
                italic = cell.xpath(".//i")
                if italic:
                    author_str = italic[0].text_content().strip()

            authors = self._parse_authors(author_str)

            # Abstract --- look for elements whose class contains "abstract"
            abstract = ""
            if cell is not None:
                abs_el = cell.xpath(
                    ".//*[contains(@class, 'abstract') or contains(@class, 'abstract-text')]"
                )
                if abs_el:
                    abstract = abs_el[0].text_content().strip()
                elif "abstract" in cell.text_content().lower():
                    # Fallback: extract text after "abstract" marker
                    text_content = cell.text_content()
                    idx = text_content.lower().find("abstract")
                    if idx >= 0:
                        abstract = text_content[idx + 8 :].strip().lstrip(": ")

            papers.append(
                self._parse(
                    {
                        "title": title,
                        "authors": authors,
                        "abstract": abstract,
                        "source_url": source_url,
                    }
                )
            )

        return SearchResult(
            papers=tuple(papers),
            total_estimated=len(papers),
            source=self.name,
        )

    @staticmethod
    def _parse_authors(raw: str) -> tuple[Author, ...]:
        """Parse author string into Author tuples.

        Handles formats: "Doe, John; Smith, Jane" and "John Doe, Jane Smith".
        """
        if not raw:
            return ()

        authors: list[Author] = []
        parts = raw.split(";") if ";" in raw else [raw]

        for part in parts:
            part = part.strip().strip(",").strip()
            if not part:
                continue
            if "," in part:
                family, given = part.split(",", 1)
                authors.append(Author(family=family.strip(), given=given.strip()))
            else:
                words = part.split()
                if len(words) >= 2:
                    authors.append(
                        Author(
                            given=" ".join(words[:-1]),
                            family=words[-1],
                        )
                    )
                else:
                    authors.append(Author(family=part))

        return tuple(authors)

    def _parse(self, item: dict[str, Any]) -> Paper:
        return Paper(
            title=item.get("title", ""),
            authors=item.get("authors", ()),
            abstract=item.get("abstract", ""),
            source_url=item.get("source_url", ""),
            source=self.name,
            oa_status="unknown",
            venue=Venue(name="SSRN", short_name="SSRN", type="repository"),
        )
