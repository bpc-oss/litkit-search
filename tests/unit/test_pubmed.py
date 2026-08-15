"""Tests for PubMed source (mocked HTTP via respx)."""

import pytest
import respx

from litkit.config import EnvConfig
from litkit.sources.pubmed import PubMed

_ESEARCH_XML = """<?xml version="1.0"?>
<eSearchResult>
  <Count>1</Count>
  <IdList><Id>12345678</Id></IdList>
</eSearchResult>"""

_ESUMMARY_JSON = {
    "result": {
        "uids": ["12345678"],
        "12345678": {
            "uid": "12345678",
            "title": "Test PubMed Paper",
            "source": "Test Journal",
            "issn": "1234-5678",
            "pubdate": "2023 May",
            "volume": "10",
            "issue": "2",
            "pages": "100-110",
            "authors": [{"name": "Doe J"}],
            "articleids": [
                {"idtype": "doi", "value": "10.1234/test"},
                {"idtype": "pmc", "value": "PMC123456"},
            ],
            "abstract": "This is a test abstract.",
            "keywords": ["Machine Learning", "AI"],
            "meshterms": ["Computers", "Algorithms"],
        },
    }
}


@pytest.fixture
def config():
    return EnvConfig(pubmed_email="test@example.com", pubmed_key="test-key")


@pytest.mark.asyncio
@respx.mock
async def test_search(config):
    esearch = respx.post("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi").respond(
        200, text=_ESEARCH_XML
    )
    esummary = respx.post("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi").respond(
        200, json=_ESUMMARY_JSON
    )
    src = PubMed(config)
    result = await src.search("machine learning", limit=10)
    assert esearch.called and esummary.called
    assert len(result.papers) == 1
    p = result.papers[0]
    assert p.title == "Test PubMed Paper"
    assert p.doi == "10.1234/test"
    assert p.year == 2023
    assert p.authors[0].family == "Doe"
    assert p.authors[0].given == "J"
    assert p.venue.name == "Test Journal"
    assert p.extra.get("pmid") == "12345678"
    assert p.extra.get("pmcid") == "PMC123456"


@pytest.mark.asyncio
@respx.mock
async def test_search_empty(config):
    respx.post("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi").respond(
        200,
        text="""<?xml version="1.0"?><eSearchResult><Count>0</Count><IdList/></eSearchResult>""",
    )
    src = PubMed(config)
    result = await src.search("nothing")
    assert len(result.papers) == 0


@pytest.mark.asyncio
@respx.mock
async def test_fetch_by_doi(config):
    respx.post("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi").respond(
        200, text=_ESEARCH_XML
    )
    respx.post("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi").respond(
        200, json=_ESUMMARY_JSON
    )
    src = PubMed(config)
    p = await src.fetch_by_doi("10.1234/test")
    assert p is not None
    assert p.doi == "10.1234/test"
