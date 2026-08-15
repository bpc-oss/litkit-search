"""Rate-limiting helpers for polite API access.

Wraps httpx async clients with tenacity retry + per-source rate limits.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


@dataclass(frozen=True)
class RateLimit:
    """Per-source rate limit configuration."""

    requests_per_second: float = 10.0
    max_retries: int = 3
    min_wait: float = 1.0
    max_wait: float = 60.0


# Common rate limits (requests/second)
RATE_LIMITS: dict[str, RateLimit] = {
    "openalex": RateLimit(requests_per_second=10.0),
    "crossref": RateLimit(requests_per_second=50.0, max_retries=5),
    "semantic_scholar": RateLimit(requests_per_second=10.0),
    "pubmed": RateLimit(requests_per_second=10.0),
    "scopus": RateLimit(requests_per_second=9.0),
    "wos": RateLimit(requests_per_second=5.0),
    "arxiv": RateLimit(requests_per_second=3.0),
    "unpaywall": RateLimit(requests_per_second=10.0),
    "core": RateLimit(requests_per_second=5.0),
    "ssrn": RateLimit(requests_per_second=2.0),
    "ieee_xplore": RateLimit(requests_per_second=10.0),
    "acm": RateLimit(requests_per_second=10.0),
    "springer": RateLimit(requests_per_second=10.0),
    "dimensions": RateLimit(requests_per_second=5.0),
    "orcid": RateLimit(requests_per_second=10.0),
    "scite": RateLimit(requests_per_second=5.0),
    "annas_archive": RateLimit(requests_per_second=2.0),
    "openalex_download": RateLimit(requests_per_second=100.0),
}


def http_retry(rate_limit: RateLimit) -> Callable[..., Any]:
    """Decorate an async function with HTTP retry logic."""

    def _is_retryable(exc: BaseException) -> bool:
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in (429, 502, 503, 504)
        return isinstance(exc, (httpx.TimeoutException, httpx.ConnectError))

    return retry(  # type: ignore[call-overload,no-any-return]
        retry=retry_if_exception_type(
            (httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError)
        ),
        stop=stop_after_attempt(rate_limit.max_retries),
        wait=wait_exponential(
            min=rate_limit.min_wait,
            max=rate_limit.max_wait,
        ),
        retry_state_callback=_is_retryable,
    )


class TokenBucket:
    """Simple async token bucket for per-source rate limiting."""

    def __init__(self, rate: float):
        self._rate = rate
        self._tokens = rate
        self._last_refill: float | None = None
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = asyncio.get_event_loop().time()
            if self._last_refill is None:
                self._last_refill = now
            elapsed = now - self._last_refill
            self._tokens = min(self._rate, self._tokens + elapsed * self._rate)
            self._last_refill = now
            if self._tokens < 1:
                sleep_time = (1 - self._tokens) / self._rate
                await asyncio.sleep(sleep_time)
                self._tokens = 0
                self._last_refill = asyncio.get_event_loop().time()
            else:
                self._tokens -= 1


_global_buckets: dict[str, TokenBucket] = {}


def bucket_for(source: str) -> TokenBucket:
    """Get or create a token bucket for *source*."""
    if source not in _global_buckets:
        rl = RATE_LIMITS.get(source, RateLimit())
        _global_buckets[source] = TokenBucket(rl.requests_per_second)
    return _global_buckets[source]
