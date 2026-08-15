"""Tests for the token-bucket rate limiter."""

import pytest

from litkit.core.ratelimit import RATE_LIMITS, TokenBucket, bucket_for


def test_token_bucket_init():
    b = TokenBucket(rate=10)
    assert b is not None


@pytest.mark.asyncio
async def test_token_bucket_acquire():
    b = TokenBucket(rate=100)
    await b.acquire()


def test_bucket_for_registered():
    _ = bucket_for("openalex")
    rl = RATE_LIMITS["openalex"]
    assert rl.requests_per_second == 10.0


def test_bucket_for_unregistered():
    b = bucket_for("nonexistent")
    assert b is not None


def test_rate_limits_config():
    assert "openalex" in RATE_LIMITS
    assert RATE_LIMITS["openalex"].requests_per_second == 10.0
    assert RATE_LIMITS["crossref"].requests_per_second == 50.0
    assert RATE_LIMITS["crossref"].max_retries == 5
    assert RATE_LIMITS["wos"].requests_per_second == 5.0
