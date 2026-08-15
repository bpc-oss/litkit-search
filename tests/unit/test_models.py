"""Tests for core models — Paper, Author, Venue, dedup, normalize_doi."""

import pydantic
import pytest

from litkit.core.models import Author, Paper, fuzzy_match, normalize_doi


class TestAuthor:
    def test_full_name(self):
        a = Author(given="John", family="Doe")
        assert a.full == "Doe, John"

    def test_full_name_no_given(self):
        a = Author(family="Doe")
        assert a.full == "Doe"

    def test_full_name_empty(self):
        a = Author()
        assert a.full == ""


class TestPaper:
    def test_minimal_paper(self):
        p = Paper(title="Test Title")
        assert p.title == "Test Title"
        assert p.doi == ""
        assert p.year == 0

    def test_doi_normalization(self):
        p = Paper(doi=" 10.1234/ABC  ")
        assert p.doi == "10.1234/abc"

    def test_id_from_doi(self):
        p = Paper(doi="10.1234/test")
        assert p.id == "10.1234/test"

    def test_id_synthetic(self):
        p = Paper(title="Some Paper", year=2023)
        assert len(p.id) == 16

    def test_immutable(self):
        p = Paper(title="Immutable")
        with pytest.raises(pydantic.ValidationError):
            p.title = "changed"

    def test_authors_tuple(self):
        authors = (Author(given="A", family="B"),)
        p = Paper(title="With Authors", authors=authors)
        assert p.authors[0].family == "B"


class TestNormalizeDOI:
    def test_bare_doi(self):
        assert normalize_doi("10.1234/abc") == "10.1234/abc"

    def test_url_doi(self):
        assert normalize_doi("https://doi.org/10.1234/def") == "10.1234/def"

    def test_case_insensitive(self):
        assert normalize_doi("10.1234/ABC") == "10.1234/abc"

    def test_doi_with_prefix(self):
        assert normalize_doi("doi:10.1234/test") == "10.1234/test"

    def test_empty(self):
        assert normalize_doi("") is None


class TestFuzzyMatch:
    def test_doi_match(self):
        a = Paper(doi="10.1/a", title="Paper A")
        b = Paper(doi="10.1/a", title="Paper B")
        assert fuzzy_match(a, b)

    def test_title_year_match(self):
        a = Paper(title=" Hello World! ", year=2023)
        b = Paper(title="hello world", year=2023)
        assert fuzzy_match(a, b)

    def test_no_match(self):
        a = Paper(title="One", year=2020)
        b = Paper(title="Two", year=2021)
        assert not fuzzy_match(a, b)
