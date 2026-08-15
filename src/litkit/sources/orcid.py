"""ORCID search source — researcher lookup, not paper search.

ORCID public API: https://pub.orcid.org/v3.0/
No API key needed for public read access.

This source is primarily useful for looking up researchers by ORCID iD
rather than searching for papers. The standard SearchSource methods
(search / fetch_by_doi) return empty / None because ORCID does not
provide keyword paper search or paper metadata by DOI.

The extra method *fetch_by_orcid* retrieves works for a specific ORCID iD.
"""

from __future__ import annotations

from typing import Any

import httpx

from litkit.core.models import Paper, SearchResult, Venue
from litkit.sources import register
from litkit.sources.base import SearchSource


@register
class ORCID(SearchSource):
    name = "orcid"
    rate_limit_key = "orcid"

    def __init__(self, config: Any, client: httpx.AsyncClient | None = None):
        super().__init__(config, client)
        self._base = "https://pub.orcid.org/v3.0"
        self._headers = {
            "Accept": "application/json",
        }

    async def search(self, query: str, limit: int = 20, **kwargs: Any) -> SearchResult:
        """Search for researchers by name.

        ORCID does not support keyword paper search. This method is a
        stub that returns an empty SearchResult. Use *fetch_by_orcid*
        to retrieve works for a known ORCID iD.
        """
        return SearchResult(source=self.name)

    async def fetch_by_doi(self, doi: str) -> Paper | None:
        """Fetch a single paper by DOI.

        ORCID does not provide paper metadata via DOI lookup.
        Always returns None.
        """
        return None

    async def fetch_by_orcid(self, orcid: str) -> list[Paper]:
        """Fetch works for a specific ORCID iD.

        Parameters
        ----------
        orcid : str
            The ORCID iD (e.g. "0000-0002-1825-0097").

        Returns
        -------
        list[Paper]
            List of papers associated with this ORCID iD.
        """
        resp = await self._rate_limited(
            self._client.get(
                f"{self._base}/{orcid}/works",
                headers=self._headers,
            )
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json()

        groups = data.get("group", [])
        papers: list[Paper] = []
        for group in groups:
            for summary in group.get("work-summary", []):
                paper = self._parse_work_summary(summary)
                if paper:
                    papers.append(paper)
        return papers

    def _parse_work_summary(self, summary: dict[str, Any]) -> Paper | None:
        """Parse a single ORCID work summary into a Paper."""
        title_data = summary.get("title", {})
        title_value = title_data.get("title", {})
        title = (title_value or {}).get("value", "")

        if not title:
            return None

        # DOI
        external_ids = summary.get("external-ids", {}).get("external-id", [])
        doi = ""
        for ext_id in external_ids:
            if ext_id.get("external-id-type", "").lower() == "doi":
                doi = (ext_id.get("external-id-value") or "").lower()
                break

        # Publication date
        pub_date = summary.get("publication-date", {}) or {}
        year = pub_date.get("year", {})
        year_val = int(year.get("value", 0)) if year else 0

        # Journal / venue
        journal_title = summary.get("journal-title", {}) or {}
        venue_name = journal_title.get("value") or ""

        # Type mapping
        work_type = summary.get("type", "")
        venue = Venue(
            name=venue_name,
            type=self._map_type(work_type),
        )

        return Paper(
            doi=doi,
            title=title,
            venue=venue,
            year=year_val,
            source=self.name,
            extra={"orcid_type": work_type},
        )

    @staticmethod
    def _map_type(work_type: str) -> str:
        """Map ORCID work types to internal venue types."""
        mapping = {
            "journal-article": "journal",
            "conference-paper": "conference",
            "book": "book",
            "book-chapter": "book-chapter",
            "dissertation": "thesis",
            "report": "report",
            "preprint": "preprint",
            "dataset": "dataset",
        }
        return mapping.get(work_type, "")
