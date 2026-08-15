"""Tests for Zotero RDF exporter."""

from litkit.core.models import Author, Paper, Venue
from litkit.exporters.zotero_rdf import zotero_rdf_string


def _make_paper(**kw) -> Paper:
    defaults = {
        "doi": "10.1234/test",
        "title": "Test Paper Title",
        "authors": (Author(given="John", family="Doe"),),
        "venue": Venue(
            name="Test Journal",
            publisher="Test Publisher",
            type="journal",
        ),
        "year": 2023,
        "volume": "10",
        "issue": "2",
        "pages": "100-110",
        "abstract": "A test abstract.",
        "source": "test_source",
    }
    defaults.update(kw)
    return Paper(**defaults)


class TestZoteroRDF:
    def test_write_zotero_rdf(self):
        p = _make_paper()
        output = zotero_rdf_string([p])

        # Root element
        assert "<rdf:RDF" in output
        assert 'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"' in output
        assert 'xmlns:bib="http://purl.org/net/biblio/"' in output
        assert 'xmlns:dc="http://purl.org/dc/elements/1.1/"' in output
        assert 'xmlns:dcterms="http://purl.org/dc/terms/"' in output
        assert 'xmlns:foaf="http://xmlns.com/foaf/0.1/"' in output

        # Article with DOI about
        assert 'rdf:about="http://doi.org/10.1234/test"' in output

        # Core fields
        assert "<dc:title>Test Paper Title</dc:title>" in output
        assert "<foaf:surname>Doe</foaf:surname>" in output
        assert "<foaf:givenname>John</foaf:givenname>" in output
        assert "<dc:date>2023</dc:date>" in output
        assert "<bib:journal>Test Journal</bib:journal>" in output
        assert "<bib:volume>10</bib:volume>" in output
        assert "<bib:issue>2</bib:issue>" in output
        assert "<bib:start>100</bib:start>" in output
        assert "<bib:end>110</bib:end>" in output
        assert "<dcterms:abstract>A test abstract.</dcterms:abstract>" in output
        assert "<dc:publisher>Test Publisher</dc:publisher>" in output

        # Identifier
        assert 'rdf:resource="http://doi.org/10.1234/test"' in output

        # Close tags
        assert "</bib:Article>" in output
        assert "</rdf:RDF>" in output

    def test_zotero_rdf_string(self):
        p = _make_paper()
        output = zotero_rdf_string([p])
        assert isinstance(output, str)
        assert len(output) > 0
        assert output.startswith("<?xml")
        assert output.strip().endswith("</rdf:RDF>")

    def test_multiple_papers(self):
        papers = [
            _make_paper(doi="10.1234/one", title="Paper One"),
            _make_paper(doi="10.1234/two", title="Paper Two"),
        ]
        output = zotero_rdf_string(papers)
        assert output.count("<dc:title>") == 2

    def test_empty_paper(self):
        p = Paper()
        output = zotero_rdf_string([p])
        assert "<rdf:RDF" in output
        assert "</rdf:RDF>" in output

    def test_conference_type(self):
        p = _make_paper(venue=Venue(name="Test Conference", type="conference"))
        output = zotero_rdf_string([p])
        assert "bib:ConferenceProceedings" in output

    def test_book_type(self):
        p = _make_paper(venue=Venue(name="Test Book", type="book"))
        output = zotero_rdf_string([p])
        assert "bib:Book" in output

    def test_no_doi(self):
        p = _make_paper(doi="", source_url="https://example.com/paper")
        output = zotero_rdf_string([p])
        assert 'rdf:about="https://example.com/paper"' in output
