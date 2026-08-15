"""Tests for the search pipeline."""

import asyncio
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from litkit.config import EnvConfig
from litkit.core.cache import MetadataCache
from litkit.core.models import Paper, SearchResult
from litkit.core.pipeline import Pipeline
from litkit.sources import _registry, register


# Register a minimal fake source for testing
@register
class FakeSource:
    name = "test_fake"
    rate_limit_key = "test_fake"

    def __init__(self, config, client=None):
        self._config = config
        self._client = client

    async def search(self, query, limit=20, **kwargs):
        return SearchResult(
            papers=(
                Paper(doi="10.1234/fake1", title=f"Fake {query}", source=self.name),
                Paper(doi="10.1234/fake2", title=f"Fake {query} 2", source=self.name),
            ),
            total_estimated=2,
            source=self.name,
        )

    async def fetch_by_doi(self, doi):
        if doi == "10.1234/fake1":
            return Paper(doi=doi, title="Fake Paper 1", source=self.name)
        return None

    async def close(self):
        pass


@pytest.fixture
def pipeline():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    cache = MetadataCache(db_path)
    pl = Pipeline(config=EnvConfig(), cache=cache)
    yield pl
    cache.close()
    Path(db_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_search(pipeline):
    papers = await pipeline.search("test query", sources=["test_fake"])
    assert len(papers) >= 2
    assert any(p.doi == "10.1234/fake1" for p in papers)
    assert all(p.source == "test_fake" for p in papers)


@pytest.mark.asyncio
async def test_search_with_source_filter(pipeline):
    papers = await pipeline.search("test", sources=["test_fake"])
    assert len(papers) == 2
    assert all(p.source == "test_fake" for p in papers)


@pytest.mark.asyncio
async def test_fetch_by_doi_found(pipeline):
    p = await pipeline.fetch_by_doi("10.1234/fake1", sources=["test_fake"])
    assert p is not None
    assert p.title == "Fake Paper 1"


@pytest.mark.asyncio
async def test_fetch_by_doi_not_found(pipeline):
    p = await pipeline.fetch_by_doi("10.9999/nonexistent", sources=["test_fake"])
    assert p is None


@pytest.mark.asyncio
async def test_download_pdfs(pipeline):
    papers = [Paper(doi="10.1234/test-dl", title="Test Download")]
    results = await pipeline.download_pdfs(papers)
    assert "10.1234/test-dl" in results


@register
class FailingSource:
    name = "test_failing"
    rate_limit_key = "test_failing"

    def __init__(self, config, client=None):
        self._config = config
        self._client = client

    async def search(self, query, limit=20, **kwargs):
        raise RuntimeError("temporary source failure")

    async def fetch_by_doi(self, doi):
        return None

    async def close(self):
        pass


@register
class ClosableSource:
    name = "test_closable"
    rate_limit_key = "test_closable"
    instances = []

    def __init__(self, config, client=None):
        self._config = config
        self._client = client
        self.closed = False
        self.__class__.instances.append(self)

    async def search(self, query, limit=20, **kwargs):
        return SearchResult(
            papers=(Paper(doi="10.1234/closable", title="Closable", source=self.name),),
            total_estimated=1,
            source=self.name,
        )

    async def fetch_by_doi(self, doi):
        if doi == "10.1234/closable":
            return Paper(doi=doi, title="Closable", source=self.name)
        return None

    async def close(self):
        self.closed = True


@register
class MergeSourceA:
    name = "test_merge_a"
    rate_limit_key = "test_merge_a"

    def __init__(self, config, client=None):
        self._config = config
        self._client = client

    async def search(self, query, limit=20, **kwargs):
        return SearchResult(
            papers=(
                Paper(doi="10.4321/merge", title="Merged Paper", source=self.name, year=2026),
            ),
            total_estimated=1,
            source=self.name,
        )

    async def fetch_by_doi(self, doi):
        if doi == "10.4321/merge":
            return Paper(doi=doi, title="Merged Paper", source=self.name, year=2026)
        return None

    async def close(self):
        pass


@register
class MergeSourceB:
    name = "test_merge_b"
    rate_limit_key = "test_merge_b"

    def __init__(self, config, client=None):
        self._config = config
        self._client = client

    async def search(self, query, limit=20, **kwargs):
        return SearchResult(
            papers=(
                Paper(
                    doi="10.4321/merge",
                    title="",
                    source=self.name,
                    pdf_url="https://example.com/merged.pdf",
                    oa_status="gold",
                ),
            ),
            total_estimated=1,
            source=self.name,
        )

    async def fetch_by_doi(self, doi):
        if doi == "10.4321/merge":
            return Paper(
                doi=doi,
                title="",
                source=self.name,
                pdf_url="https://example.com/merged.pdf",
                oa_status="gold",
            )
        return None

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_search_ignores_failing_source():
    original = _registry.copy()
    cache = MetadataCache()
    pipeline = Pipeline(config=EnvConfig(), cache=cache)
    try:
        papers = await pipeline.search("test", sources=["test_failing"])
        assert papers == []
    finally:
        _registry.clear()
        _registry.update(original)
        cache.close()


@pytest.mark.asyncio
async def test_search_audits_unknown_source(tmp_path):
    db_path = tmp_path / "cache.db"
    cache = MetadataCache(db_path)
    pipeline = Pipeline(config=EnvConfig(), cache=cache)
    try:
        papers = await pipeline.search("test", sources=["missing_source"])
        assert papers == []
        audit = cache.recent_audit()
        assert audit[0]["action"] == "unknown_source"
        assert "missing_source" in audit[0]["detail"]
    finally:
        cache.close()


@pytest.mark.asyncio
async def test_search_closes_sources(pipeline):
    ClosableSource.instances.clear()

    papers = await pipeline.search("test", sources=["test_closable"])

    assert len(papers) == 1
    assert ClosableSource.instances
    assert all(instance.closed for instance in ClosableSource.instances)


@pytest.mark.asyncio
async def test_fetch_by_doi_closes_sources(pipeline):
    ClosableSource.instances.clear()

    paper = await pipeline.fetch_by_doi("10.1234/closable", sources=["test_closable"])

    assert paper is not None
    assert ClosableSource.instances
    assert all(instance.closed for instance in ClosableSource.instances)


@pytest.mark.asyncio
async def test_fetch_by_doi_merges_complementary_source_metadata(pipeline):
    paper = await pipeline.fetch_by_doi("10.4321/merge", sources=["test_merge_a", "test_merge_b"])

    assert paper is not None
    assert paper.title == "Merged Paper"
    assert paper.pdf_url == "https://example.com/merged.pdf"
    assert paper.oa_status == "gold"
    assert paper.source == "test_merge_a+test_merge_b"


@pytest.mark.asyncio
async def test_fetch_by_doi_enriches_cached_record(pipeline):
    pipeline._cache.put_paper(Paper(doi="10.4321/merge", title="Merged Paper", source="crossref"))

    paper = await pipeline.fetch_by_doi("10.4321/merge", sources=["test_merge_b"])

    assert paper is not None
    assert paper.pdf_url == "https://example.com/merged.pdf"
    assert paper.oa_status == "gold"
    assert paper.source == "crossref+test_merge_b"


@pytest.mark.asyncio
async def test_download_pdfs_runs_with_limited_concurrency(monkeypatch, pipeline, tmp_path):
    class FakeChain:
        def __init__(self, cache, config):
            self._dest = tmp_path

        def add(self, downloader):
            pass

        async def download(self, paper):
            await asyncio.sleep(0.1)
            safe_id = paper.id.replace("/", "_")
            path = self._dest / f"{safe_id}.pdf"
            path.write_bytes(b"%PDF-test")
            return path

        async def close(self):
            pass

    class FakeDownloader:
        def __init__(self, cache, config):
            pass

    monkeypatch.setattr("litkit.downloaders.DownloadChain", FakeChain)
    monkeypatch.setattr(pipeline, "fetch_by_doi", AsyncMock(return_value=None))
    for name in [
        "ArxivDownloader",
        "BiorxivDownloader",
        "UnpaywallDownloader",
        "EuropePmcDownloader",
        "PmcFtpDownloader",
        "PublisherDirectDownloader",
        "SciHubDownloader",
        "LibgenDownloader",
        "AnnasArchiveDownloader",
        "ChineseInstitutionalDownloader",
        "InstitutionalDownloader",
    ]:
        monkeypatch.setattr(f"litkit.downloaders.{name}", FakeDownloader)

    papers = [Paper(doi=f"10.1234/test-{i}", title=f"Paper {i}") for i in range(4)]

    start = time.perf_counter()
    results = await pipeline.download_pdfs(papers, max_concurrency=3)
    elapsed = time.perf_counter() - start

    assert len(results) == 4
    assert elapsed < 0.35


@pytest.mark.asyncio
async def test_download_pdfs_enriches_metadata_before_download(monkeypatch, pipeline, tmp_path):
    class FakeChain:
        def __init__(self, cache, config):
            self.seen_pdf_urls = []
            self._dest = tmp_path

        def add(self, downloader):
            pass

        async def download(self, paper):
            self.seen_pdf_urls.append(paper.pdf_url)
            safe_id = paper.id.replace("/", "_")
            path = self._dest / f"{safe_id}.pdf"
            path.write_bytes(b"%PDF-test")
            return path

        async def close(self):
            pass

    class FakeDownloader:
        def __init__(self, cache, config):
            pass

    fake_chain = FakeChain(None, None)

    async def fake_fetch_by_doi(doi, sources=None):
        return Paper(
            doi=doi,
            title="Enriched",
            pdf_url="https://example.com/enriched.pdf",
            source="test_merge_b",
        )

    monkeypatch.setattr("litkit.downloaders.DownloadChain", lambda cache, config: fake_chain)
    monkeypatch.setattr(pipeline, "fetch_by_doi", fake_fetch_by_doi)
    for name in [
        "ArxivDownloader",
        "BiorxivDownloader",
        "UnpaywallDownloader",
        "EuropePmcDownloader",
        "PmcFtpDownloader",
        "PublisherDirectDownloader",
        "SciHubDownloader",
        "LibgenDownloader",
        "AnnasArchiveDownloader",
        "ChineseInstitutionalDownloader",
        "InstitutionalDownloader",
    ]:
        monkeypatch.setattr(f"litkit.downloaders.{name}", FakeDownloader)

    papers = [Paper(doi="10.1234/enrich-me", title="Paper")]
    results = await pipeline.download_pdfs(papers)

    assert results["10.1234/enrich-me"] is not None
    assert fake_chain.seen_pdf_urls == ["https://example.com/enriched.pdf"]
