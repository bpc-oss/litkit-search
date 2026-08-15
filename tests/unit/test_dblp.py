"""Tests for DBLP source (mocked HTTP via respx)."""

import pytest
import respx

from litkit.config import EnvConfig
from litkit.sources.dblp import DBLP


@pytest.fixture
def config():
    return EnvConfig()


_BASE = "https://dblp.org/search/publ/api"


@pytest.mark.asyncio
@respx.mock
async def test_search(config):
    respx.get(_BASE).respond(
        200,
        text="""<?xml version="1.0"?>
<hits total="1" computed="1" xmlns:h="http://dblp.org/search/">
  <h:hit>
    <info>
      <title>Test DBLP Paper</title>
      <year>2023</year>
      <venue>Test Conference</venue>
      <authors>
        <author>John Doe</author>
      </authors>
      <doi>10.1234/dblp-test</doi>
      <url>https://dblp.org/rec/abc123</url>
    </info>
  </h:hit>
</hits>""",
    )
    src = DBLP(config)
    result = await src.search("test query", limit=10)
    assert len(result.papers) == 1
    p = result.papers[0]
    assert p.doi == "10.1234/dblp-test"
    assert p.title == "Test DBLP Paper"
    assert p.year == 2023


@pytest.mark.asyncio
@respx.mock
async def test_search_empty(config):
    respx.get(_BASE).respond(
        200,
        text='<?xml version="1.0"?><hits total="0" computed="0"/>',
    )
    src = DBLP(config)
    result = await src.search("nothing")
    assert len(result.papers) == 0


@pytest.mark.asyncio
@respx.mock
async def test_fetch_by_doi(config):
    respx.get(_BASE).respond(
        200,
        text="""<?xml version="1.0"?>
<hits total="1" computed="1">
  <hit>
    <info>
      <title>Found by DOI</title>
      <year>2023</year>
      <doi>10.1234/dblp-found</doi>
    </info>
  </hit>
</hits>""",
    )
    src = DBLP(config)
    p = await src.fetch_by_doi("10.1234/dblp-found")
    assert p is not None
    assert p.title == "Found by DOI"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_by_doi_not_found(config):
    respx.get(_BASE).respond(
        200,
        text='<?xml version="1.0"?><hits total="0" computed="0"/>',
    )
    src = DBLP(config)
    p = await src.fetch_by_doi("10.9999/missing")
    assert p is None
