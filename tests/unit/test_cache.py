"""Tests for SQLite-based MetadataCache."""

import tempfile
from pathlib import Path

import pytest

from litkit.core.cache import MetadataCache
from litkit.core.models import Paper


@pytest.fixture
def cache():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    c = MetadataCache(db_path)
    yield c
    c.close()
    Path(db_path).unlink(missing_ok=True)


class TestPaperCache:
    def test_put_and_get(self, cache):
        p = Paper(doi="10.1234/test", title="Test Paper")
        cache.put_paper(p)
        retrieved = cache.get_paper(p.id)
        assert retrieved is not None
        assert retrieved.title == "Test Paper"

    def test_get_missing(self, cache):
        assert cache.get_paper("nonexistent") is None

    def test_put_papers_batch(self, cache):
        papers = [Paper(doi=f"10.1234/{i}", title=f"Paper {i}") for i in range(5)]
        cache.put_papers(papers)
        for p in papers:
            assert cache.get_paper(p.id) is not None

    def test_search_papers(self, cache):
        cache.put_paper(Paper(doi="10.1234/a", title="Machine Learning"))
        cache.put_paper(Paper(doi="10.1234/b", title="Deep Learning"))
        results = cache.search_papers("Machine")
        assert len(results) == 1
        assert results[0].title == "Machine Learning"


class TestHTTPCache:
    def test_put_and_get(self, cache):
        cache.put_http("https://example.com/api", '{"key": "value"}', ttl=3600)
        data = cache.get_http("https://example.com/api")
        assert data is not None
        assert "key" in data

    def test_expired(self, cache):
        import time

        cache.put_http("https://example.com/old", "data", ttl=0)
        time.sleep(0.01)
        assert cache.get_http("https://example.com/old") is None

    def test_put_and_get_doi_resolution(self, cache):
        cache.put_doi_resolution("10.1234/Test", "https://example.com/paper")
        assert cache.get_doi_resolution("10.1234/test") == "https://example.com/paper"

    def test_expired_doi_resolution(self, cache):
        import time

        cache.put_doi_resolution("10.1234/test", "https://example.com/old", ttl=0)
        time.sleep(0.01)
        assert cache.get_doi_resolution("10.1234/test") is None


class TestDownloaderMemory:
    def test_preferred_downloaders_promote_success(self, cache):
        cache.record_downloader_outcome("10.1109/test", "institutional", success=False)
        cache.record_downloader_outcome("10.1109/test", "publisher_direct", success=True)
        cache.record_downloader_outcome("10.1109/test", "publisher_direct", success=True)

        assert cache.preferred_downloaders("10.1109/another")[:2] == [
            "publisher_direct",
            "institutional",
        ]

    def test_preferred_downloaders_use_prefix_scope(self, cache):
        cache.record_downloader_outcome("10.1109/test", "institutional", success=True)
        assert cache.preferred_downloaders("10.9999/test") == []


class TestAuditLog:
    def test_audit(self, cache):
        cache.audit("test_action", "test detail")
        entries = cache.recent_audit(10)
        assert len(entries) >= 1
        assert entries[0]["action"] == "test_action"


class TestPDFCacheIsolation:
    def test_explicit_database_uses_adjacent_pdf_directory(self, tmp_path):
        cache = MetadataCache(tmp_path / "cache.db")
        try:
            assert cache.pdf_path("10.1234/isolation").parent == tmp_path / "cache-pdfs"
        finally:
            cache.close()

    def test_rejects_tiny_pdf_marker_file(self, tmp_path):
        cache = MetadataCache(tmp_path / "cache.db")
        try:
            path = cache.pdf_path("10.1234/tiny")
            path.write_bytes(b"%PDF-test-content")
            assert cache.has_pdf("10.1234/tiny") is False
        finally:
            cache.close()
