"""Tests for deduplication logic."""

from litkit.core.dedup import deduplicate, merge_duplicates
from litkit.core.models import Paper


def _p(doi="", title="", year=0, citations=0, source="test", abstract="", **kw) -> Paper:
    return Paper(
        doi=doi,
        title=title,
        year=year,
        citations_count=citations,
        source=source,
        abstract=abstract,
        **kw,
    )


class TestDeduplicate:
    def test_doi_dedup(self):
        papers = [_p(doi="10.1234/a"), _p(doi="10.1234/a", title="Different Title")]
        result = deduplicate(papers)
        assert len(result) == 1

    def test_title_year_dedup(self):
        papers = [
            _p(title="Hello World", year=2023),
            _p(title="Hello World", year=2023),
        ]
        result = deduplicate(papers)
        assert len(result) == 1

    def test_no_dedup(self):
        papers = [
            _p(doi="10.1234/a", title="Paper A"),
            _p(doi="10.1234/b", title="Paper B"),
        ]
        result = deduplicate(papers)
        assert len(result) == 2

    def test_empty(self):
        assert deduplicate([]) == []

    def test_preserves_order(self):
        papers = [
            _p(doi="10.1234/b", title="B"),
            _p(doi="10.1234/a", title="A"),
            _p(doi="10.1234/b", title="B Dup"),
        ]
        result = deduplicate(papers)
        assert len(result) == 2
        assert result[0].title == "B"
        assert result[1].title == "A"


class TestMergeDuplicates:
    def test_merges_fields(self):
        a = _p(doi="10.1234/a", title="Paper A", year=2023, abstract="Original abs")
        b = _p(
            doi="10.1234/a", title="Paper A", abstract="New abstract", citations=5, source="other"
        )
        result = merge_duplicates([a, b])
        assert len(result) == 1
        # First paper's non-empty field takes priority
        assert "Original abs" in (result[0].abstract or "")

    def test_combines_sources(self):
        a = _p(doi="10.1234/a", title="Paper", source="openalex")
        b = _p(doi="10.1234/a", title="Paper", source="crossref")
        result = merge_duplicates([a, b])
        assert len(result) == 1
        assert "openalex" in result[0].source
        assert "crossref" in result[0].source
