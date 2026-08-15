"""Abstract base class for all search sources.

Each source module implements SearchSource and registers via
the SOURCES registry dict. Adding a new source only requires
creating a new module that implements this ABC — no core changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import httpx

from litkit.config import EnvConfig
from litkit.core.models import Paper, SearchResult
from litkit.core.ratelimit import TokenBucket, bucket_for


class SearchSource(ABC):
    """Interface for a single literature search source.

    Subclasses set *name* (used in CLI / config) and *rate_limit_key*
    (looked up in RATE_LIMITS, defaults to name).
    """

    name: str = ""
    rate_limit_key: str = ""

    def __init__(self, config: EnvConfig, client: httpx.AsyncClient | None = None):
        self._config = config
        self._client = client or httpx.AsyncClient(timeout=30.0)
        self._bucket: TokenBucket = bucket_for(self.rate_limit_key or self.name)

    @abstractmethod
    async def search(self, query: str, limit: int = 20, **kwargs: Any) -> SearchResult:
        """Search the source for *query*.

        Returns a SearchResult with papers sorted by relevance (source
        dependent). Subclasses should respect *limit* as the desired
        number of results.
        """

    @abstractmethod
    async def fetch_by_doi(self, doi: str) -> Paper | None:
        """Fetch a single paper by DOI.

        Returns None if the DOI is not found in this source.
        """

    async def _rate_limited(self, coro: Any) -> Any:
        """Acquire token then await *coro*."""
        await self._bucket.acquire()
        return await coro

    async def close(self) -> None:
        await self._client.aclose()
