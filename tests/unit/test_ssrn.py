"""Tests for SSRN source (mocked HTTP via respx)."""

import pytest
import respx

from litkit.config import EnvConfig
from litkit.sources.ssrn import Ssrn


@pytest.fixture
def config():
    return EnvConfig()


_SAMPLE_HTML = """\
<html><body>
<table>
<tr>
<td>
<a href="/abstract=123456">A Test SSRN Paper</a><br>
<i>Doe, John; Smith, Jane</i><br>
<span class="abstract-text">This is a test abstract for an SSRN paper.</span>
</td>
</tr>
<tr>
<td>
<a href="/abstract=789012">Another SSRN Paper</a><br>
<i>Williams, Robert</i><br>
<span class="abstract-text">Abstract of the second paper.</span>
</td>
</tr>
</table>
</body></html>
"""

_EMPTY_HTML = """\
<html><body>
<p>No results found.</p>
</body></html>
"""


@pytest.mark.asyncio
@respx.mock
async def test_search_parses_html(config):
    route = respx.post("https://papers.ssrn.com/sol3/DisplayAbstractSearch.cfm").respond(
        200, text=_SAMPLE_HTML
    )
    src = Ssrn(config)
    result = await src.search("test query")
    assert route.called
    assert len(result.papers) == 2

    p1 = result.papers[0]
    assert p1.title == "A Test SSRN Paper"
    assert len(p1.authors) == 2
    assert p1.authors[0].family == "Doe"
    assert p1.authors[0].given == "John"
    assert p1.authors[1].family == "Smith"
    assert p1.authors[1].given == "Jane"
    assert "test abstract" in p1.abstract
    assert p1.source_url == "https://papers.ssrn.com/abstract=123456"
    assert p1.source == "ssrn"
    assert p1.oa_status == "unknown"
    assert p1.venue.name == "SSRN"

    p2 = result.papers[1]
    assert p2.title == "Another SSRN Paper"
    assert len(p2.authors) == 1
    assert p2.authors[0].family == "Williams"
    assert p2.authors[0].given == "Robert"


@pytest.mark.asyncio
@respx.mock
async def test_search_empty(config):
    route = respx.post("https://papers.ssrn.com/sol3/DisplayAbstractSearch.cfm").respond(
        200, text=_EMPTY_HTML
    )
    src = Ssrn(config)
    result = await src.search("nothing")
    assert route.called
    assert len(result.papers) == 0
    assert result.total_estimated == 0
