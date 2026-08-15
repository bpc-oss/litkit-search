"""DBLP â€” CS bibliography (XML API).

API: https://dblp.org/faq/13501473.html
"""

from __future__ import annotations

from typing import Any
from xml.etree import ElementTree

import httpx

from litkit.core.models import Author, Paper, SearchResult, Venue
from litkit.sources import register
from litkit.sources.base import SearchSource


@register
class DBLP(SearchSource):
    name = "dblp"
    rate_limit_key = "openalex"

    def __init__(self, config: Any, client: httpx.AsyncClient | None = None):
        super().__init__(config, client)
        self._base = "https://dblp.org/search/publ/api"

    async def search(self, query: str, limit: int = 20, **kwargs: Any) -> SearchResult:
        params = {
            "q": query,
            "h": min(limit, 100),
            "format": "xml",
        }
        resp = await self._rate_limited(self._client.get(self._base, params=params))
        resp.raise_for_status()
        root = ElementTree.fromstring(resp.content)
        ns = {"h": "http://dblp.org/search/", "p": "https://dblp.org/rdf/doc/"}
        hits = root.findall(".//h:hit", ns)
        total_el = root.find(".//h:total", ns)
        total = int(total_el.text) if total_el is not None else 0

        papers = []
        for hit in hits:
            info = hit.find("p:info", ns) or hit.find("./info", ns)
            if info is None:
                continue
            papers.append(self._parse(info))

        return SearchResult(papers=tuple(papers), total_estimated=total, source=self.name)

    async def fetch_by_doi(self, doi: str) -> Paper | None:
        resp = await self._rate_limited(
            self._client.get(
                "https://dblp.org/search/publ/api",
                params={"q": f"doi:{doi}", "h": 1, "format": "xml"},
            )
        )
        resp.raise_for_status()
        root = ElementTree.fromstring(resp.content)
        hit = root.find(".//hit")
        if hit is None:
            return None
        info = hit.find("info")
        if info is None:
            return None
        return self._parse(info)

    def _parse(self, info: Any) -> Paper:
        authors_list = []
        authors_el = info.find("authors")
        if authors_el is not None:
            for au in authors_el.findall("author"):
                name = au.text or ""
                authors_list.append(Author(family=name))

        title_el = info.find("title")
        title = title_el.text.strip() if title_el is not None and title_el.text else ""

        venue_el = info.find("venue")
        venue_name = venue_el.text.strip() if venue_el is not None and venue_el.text else ""

        year_el = info.find("year")
        year = int(year_el.text) if year_el is not None and year_el.text else 0

        doi = ""
        doi_el = info.find("doi")
        if doi_el is not None and doi_el.text:
            doi = doi_el.text.replace("https://doi.org/", "")

        pub_type = ""
        type_el = info.find("type")
        if type_el is not None and type_el.text:
            pub_type = type_el.text

        volume = ""
        vol_el = info.find("volume")
        if vol_el is not None and vol_el.text:
            volume = vol_el.text

        pages_el = info.find("pages")
        pages = pages_el.text.strip() if pages_el is not None and pages_el.text else ""

        return Paper(
            doi=doi,
            title=title,
            authors=tuple(authors_list),
            venue=Venue(name=venue_name),
            year=year,
            volume=volume,
            pages=pages,
            source=self.name,
            extra={"dblp_type": pub_type},
        )

