"""Tests for CORE source (mocked HTTP via respx)."""

import pytest
import respx

from litkit.config import EnvConfig
from litkit.sources.core import CORE


@pytest.fixture
def config():
    return EnvConfig(crossref_email="test@example.com")


_BASE = "https://api.core.ac.uk/v3"


@pytest.mark.asyncio
@respx.mock
async def test_search_no_key(config):
    src = CORE(config)
    result = await src.search("test query")
    assert len(result.papers) == 0


@pytest.mark.asyncio
@respx.mock
async def test_fetch_by_doi_without_key(config):
    src = CORE(config)
    p = await src.fetch_by_doi("10.1234/core-test")
    assert p is None


@pytest.mark.asyncio
async def test_search_returns_empty_without_key(config):
    src = CORE(config)
    result = await src.search("anything")
    assert len(result.papers) == 0
