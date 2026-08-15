"""Tests for ORCID source (mocked HTTP via respx)."""

import pytest
import respx

from litkit.config import EnvConfig
from litkit.sources.orcid import ORCID


@pytest.fixture
def config():
    return EnvConfig()


@pytest.mark.asyncio
@respx.mock
async def test_search_returns_empty(config):
    src = ORCID(config)
    result = await src.search("test query", limit=10)
    assert len(result.papers) == 0
    assert result.total_estimated == 0
    assert result.source == "orcid"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_by_doi_returns_none(config):
    src = ORCID(config)
    result = await src.fetch_by_doi("10.1234/test")
    assert result is None
