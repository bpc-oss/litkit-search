"""Shenzhen University library Chinese database gateway source."""

from __future__ import annotations

from typing import Any

import httpx

from litkit.chinese.resources import SZU_CHINESE_RESOURCES, build_search_targets
from litkit.core.models import Paper, SearchResult, Venue
from litkit.sources import register
from litkit.sources.base import SearchSource


@register
class SzuLibrary(SearchSource):
    """Return SZU-authenticated Chinese database search entry links.

    This source does not claim bibliographic metadata has been retrieved from
    CNKI/Wanfang/CQVIP. It creates gateway records that point an authenticated
    browser session to the correct resource, with SZU access notes in ``extra``.
    """

    name = "szu_library"
    rate_limit_key = "szu_library"

    def __init__(self, config: Any, client: httpx.AsyncClient | None = None):
        super().__init__(config, client)

    async def search(self, query: str, limit: int = 20, **kwargs: Any) -> SearchResult:
        requested_sources = kwargs.get("chinese_sources")
        if isinstance(requested_sources, str):
            requested_sources = [s.strip() for s in requested_sources.split(",") if s.strip()]
        targets = build_search_targets(query, requested_sources)
        papers = [
            Paper(
                title=f"{resource.label}: {query}",
                venue=Venue(name="Shenzhen University Library", type="library_gateway"),
                year=0,
                source_url=search_url,
                source=self.name,
                language="zh",
                extra={
                    "kind": "library_gateway",
                    "provider": resource.provider,
                    "resource": resource.name,
                    "library_page": resource.library_page,
                    "access_note": resource.access_note,
                    "content_types": list(resource.content_types),
                    "subscribed": resource.subscribed,
                },
            )
            for resource, search_url in targets[:limit]
        ]
        return SearchResult(
            papers=tuple(papers),
            total_estimated=len(targets),
            source=self.name,
        )

    async def fetch_by_doi(self, doi: str) -> Paper | None:
        return None


def resource_names() -> list[str]:
    return list(SZU_CHINESE_RESOURCES)
