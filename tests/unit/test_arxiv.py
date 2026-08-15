"""Tests for arXiv source (mocked HTTP via respx)."""

import pytest
import respx

from litkit.config import EnvConfig
from litkit.sources.arxiv import Arxiv

_SAMPLE_FEED = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
  <opensearch:totalResults>1</opensearch:totalResults>
  <entry>
    <id>http://arxiv.org/abs/2101.00001v1</id>
    <title>Test ArXiv Paper Title</title>
    <published>2021-01-01T00:00:00Z</published>
    <summary>This is a test abstract.</summary>
    <author><name>John Doe</name></author>
    <arxiv:primary_category term="cs.AI"/>
    <arxiv:doi>10.1234/test-arxiv</arxiv:doi>
  </entry>
</feed>"""


@pytest.fixture
def config():
    return EnvConfig()


@pytest.mark.asyncio
@respx.mock
async def test_search(config):
    route = respx.get("https://export.arxiv.org/api/query").respond(200, text=_SAMPLE_FEED)
    src = Arxiv(config)
    result = await src.search("test query", limit=10)
    assert route.called
    assert len(result.papers) == 1
    p = result.papers[0]
    assert p.title == "Test ArXiv Paper Title"
    assert p.year == 2021
    assert p.authors[0].family == "Doe"
    assert p.authors[0].given == "John"
    assert p.doi == "10.1234/test-arxiv"
    assert p.oa_status == "green"
    assert p.venue.name == "arXiv"
    assert "cs.AI" in p.subjects


@pytest.mark.asyncio
@respx.mock
async def test_search_empty(config):
    feed = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
  <opensearch:totalResults>0</opensearch:totalResults>
</feed>"""
    respx.get("https://export.arxiv.org/api/query").respond(200, text=feed)
    src = Arxiv(config)
    result = await src.search("nothing")
    assert len(result.papers) == 0
    assert result.total_estimated == 0


@pytest.mark.asyncio
@respx.mock
async def test_fetch_by_doi(config):
    respx.get("https://export.arxiv.org/api/query").respond(200, text=_SAMPLE_FEED)
    src = Arxiv(config)
    p = await src.fetch_by_doi("10.1234/test-arxiv")
    assert p is not None
    assert p.title == "Test ArXiv Paper Title"
