"""Tests for RIS, BibTeX, and CSL-JSON exporters."""

from litkit.core.models import Author, Paper, Venue
from litkit.exporters.bibtex import write_bibtex
from litkit.exporters.csljson import write_csljson
from litkit.exporters.ris import ris_string


def _make_paper(**kw) -> Paper:
    defaults = {
        "doi": "10.1234/test",
        "title": "Test Paper",
        "authors": (Author(given="John", family="Doe"),),
        "venue": Venue(
            name="Test Journal",
            short_name="Test J",
            issn="1234-5678",
            publisher="Test Pub",
            type="journal",
        ),
        "year": 2023,
        "volume": "10",
        "issue": "2",
        "pages": "100-110",
        "abstract": "A test abstract.",
        "keywords": ("ML", "AI"),
        "source": "test_source",
        "oa_status": "gold",
    }
    defaults.update(kw)
    return Paper(**defaults)


class TestRIS:
    def test_single_paper(self):
        p = _make_paper()
        output = ris_string([p])
        assert "TY  - JOUR" in output
        assert "AU  - Doe, John" in output
        assert "TI  - Test Paper" in output
        assert "JO  - Test Journal" in output
        assert "JF  - Test J" in output
        assert "VL  - 10" in output
        assert "IS  - 2" in output
        assert "SP  - 100" in output
        assert "EP  - 110" in output
        assert "PY  - 2023" in output
        assert "DO  - 10.1234/test" in output
        assert "SN  - 1234-5678" in output
        assert "PB  - Test Pub" in output
        assert "KW  - ML" in output
        assert "KW  - AI" in output
        assert "ER  -" in output

    def test_empty_paper(self):
        p = Paper()
        output = ris_string([p])
        assert "TY  - JOUR" in output
        assert "ER  -" in output

    def test_multiple_papers(self):
        papers = [_make_paper(), _make_paper(doi="10.1/test2", title="Paper 2")]
        output = ris_string(papers)
        assert output.count("ER  -") == 2


class TestBibTeX:
    def test_single_paper(self):
        p = _make_paper()
        output = write_bibtex([p])
        assert "@article{" in output
        assert "author = {Doe, John}" in output
        assert "title = {Test Paper}" in output
        assert "journal = {Test Journal}" in output
        assert "year = {2023}" in output
        assert "doi = {10.1234/test}" in output

    def test_empty_paper(self):
        p = Paper()
        output = write_bibtex([p])
        assert "@article{" in output

    def test_special_chars(self):
        p = _make_paper(title="Test & Paper with braces")
        output = write_bibtex([p])
        assert "Test" in output
        assert "\\&" in output


class TestCSLJSON:
    def test_single_paper(self):
        p = _make_paper()
        output = write_csljson([p])
        assert '"DOI": "10.1234/test"' in output
        assert '"title": "Test Paper"' in output
        assert '"family": "Doe"' in output
        assert '"given": "John"' in output

    def test_empty_paper(self):
        p = Paper()
        output = write_csljson([p])
        assert len(output) > 0  # produces valid output
