"""Tests for downloader chain and base downloader classes."""

import tempfile
from pathlib import Path

import pytest

from litkit.config import EnvConfig
from litkit.core.cache import MetadataCache
from litkit.core.models import Paper
from litkit.downloaders.base import DownloadChain


class FakeDownloader:
    """Minimal downloader for testing the chain."""

    name = "fake_downloader"

    def __init__(self, cache, config, fail=False):
        self._cache = cache
        self._config = config
        self._fail = fail
        self.called = False

    async def can_handle(self, paper):
        return True

    async def download(self, paper):
        self.called = True
        if self._fail:
            return None
        dest = self._cache.pdf_path(paper.id)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"%PDF-1.4\n" + b"0" * 1024 + b"\n%%EOF\n")
        return dest

    async def close(self):
        pass


class FilteredDownloader:
    """Downloader that only handles specific papers."""

    name = "filtered"

    def __init__(self, cache, config, target_doi=None):
        self._cache = cache
        self._config = config
        self._target_doi = target_doi
        self.called = False

    async def can_handle(self, paper):
        return paper.doi == self._target_doi

    async def download(self, paper):
        self.called = True
        dest = self._cache.pdf_path(paper.id)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"%PDF-filtered")
        return dest

    async def close(self):
        pass


class NamedDownloader(FakeDownloader):
    """Downloader with a configurable name for preference-order tests."""

    def __init__(self, cache, config, name, fail=False):
        super().__init__(cache, config, fail=fail)
        self.name = name


class InvalidDownloader(FakeDownloader):
    async def download(self, paper):
        self.called = True
        dest = self._cache.pdf_path(paper.id)
        dest.write_bytes(b"%PDF-test-content")
        return dest


@pytest.fixture
def cache():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    c = MetadataCache(db_path)
    yield c
    c.close()
    Path(db_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_chain_first_success(cache):
    chain = DownloadChain(cache, EnvConfig())
    d1 = FakeDownloader(cache, EnvConfig())
    chain.add(d1)
    paper = Paper(doi="10.1234/test-chain", title="Test")
    result = await chain.download(paper)
    assert result is not None
    assert result.name.endswith(".pdf")
    await chain.close()


@pytest.mark.asyncio
async def test_chain_fallback(cache):
    chain = DownloadChain(cache, EnvConfig())
    fail = FakeDownloader(cache, EnvConfig(), fail=True)
    success = FakeDownloader(cache, EnvConfig())
    chain.add(fail)
    chain.add(success)
    paper = Paper(doi="10.1234/fallback", title="Test")
    result = await chain.download(paper)
    assert result is not None
    assert fail.called
    assert success.called
    await chain.close()


@pytest.mark.asyncio
async def test_chain_all_fail(cache):
    chain = DownloadChain(cache, EnvConfig())
    d1 = FakeDownloader(cache, EnvConfig(), fail=True)
    chain.add(d1)
    paper = Paper(doi="10.1234/allfail", title="Test")
    result = await chain.download(paper)
    assert result is None
    await chain.close()


@pytest.mark.asyncio
async def test_chain_respects_can_handle(cache):
    chain = DownloadChain(cache, EnvConfig())
    filtered = FilteredDownloader(cache, EnvConfig(), target_doi="10.1234/specific")
    chain.add(filtered)
    paper = Paper(doi="10.1234/other", title="Test")
    result = await chain.download(paper)
    assert result is None
    assert not filtered.called
    await chain.close()


@pytest.mark.asyncio
async def test_chain_cached_pdf(cache):
    paper = Paper(doi="10.1234/cached", title="Test")
    pdf_path = cache.pdf_path(paper.id)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(b"%PDF-1.4\n" + b"0" * 1024 + b"\n%%EOF\n")

    chain = DownloadChain(cache, EnvConfig())
    success = FakeDownloader(cache, EnvConfig())
    chain.add(success)
    result = await chain.download(paper)
    assert result is not None
    assert not success.called  # Should not call downloader
    await chain.close()


@pytest.mark.asyncio
async def test_chain_rejects_invalid_downloader_output(cache):
    chain = DownloadChain(cache, EnvConfig())
    invalid = InvalidDownloader(cache, EnvConfig())
    chain.add(invalid)
    paper = Paper(doi="10.1234/invalid-output", title="Invalid")

    result = await chain.download(paper)

    assert result is None
    assert not cache.pdf_path(paper.id).exists()
    await chain.close()


@pytest.mark.asyncio
async def test_chain_reorders_using_prefix_memory(cache):
    cache.record_downloader_outcome("10.1109/example", "institutional", success=True)
    cache.record_downloader_outcome("10.1109/example", "publisher_direct", success=False)

    chain = DownloadChain(cache, EnvConfig())
    first = NamedDownloader(cache, EnvConfig(), "publisher_direct", fail=True)
    second = NamedDownloader(cache, EnvConfig(), "institutional")
    chain.add(first)
    chain.add(second)

    paper = Paper(doi="10.1109/test-chain-memory", title="Test")
    result = await chain.download(paper)

    assert result is not None
    assert second.called
    assert not first.called
    await chain.close()


@pytest.mark.asyncio
async def test_chain_records_downloader_outcomes(cache):
    chain = DownloadChain(cache, EnvConfig())
    fail = NamedDownloader(cache, EnvConfig(), "publisher_direct", fail=True)
    success = NamedDownloader(cache, EnvConfig(), "institutional")
    chain.add(fail)
    chain.add(success)

    paper = Paper(doi="10.1109/test-recording", title="Test")
    result = await chain.download(paper)

    assert result is not None
    assert cache.preferred_downloaders("10.1109/next")[:2] == [
        "institutional",
        "publisher_direct",
    ]
    await chain.close()
