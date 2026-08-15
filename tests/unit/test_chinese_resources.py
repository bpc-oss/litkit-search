"""Tests for Chinese literature resource support."""

from pathlib import Path

import pytest

from litkit.chinese.resources import build_search_targets
from litkit.config import EnvConfig
from litkit.core.cache import MetadataCache
from litkit.core.models import Paper
from litkit.downloaders.chinese_institutional import ChineseInstitutionalDownloader
from litkit.sources import get


def test_build_search_targets_encodes_query():
    targets = build_search_targets("肠道菌群", ["cnki", "wanfang"])
    assert len(targets) == 2
    assert targets[0][0].name == "cnki"
    assert "%E8%82%A0%E9%81%93%E8%8F%8C%E7%BE%A4" in targets[0][1]


@pytest.mark.asyncio
async def test_szu_library_source_returns_gateway_records():
    source_cls = get("szu_library")
    source = source_cls(EnvConfig())
    result = await source.search("肠道菌群", limit=2)
    assert result.source == "szu_library"
    assert len(result.papers) == 2
    assert result.papers[0].language == "zh"
    assert result.papers[0].extra["kind"] == "library_gateway"
    await source.close()


@pytest.mark.asyncio
async def test_chinese_downloader_queues_without_direct_pdf(tmp_path):
    db_path = tmp_path / "cache.db"
    queue_path = tmp_path / "queue.csv"
    cache = MetadataCache(db_path)
    config = EnvConfig(chinese_acquisition_queue=str(queue_path))
    downloader = ChineseInstitutionalDownloader(cache, config)
    paper = Paper(
        title="中文测试文献",
        source="szu_library",
        source_url="",
        language="zh",
        extra={"provider": "cnki"},
    )

    try:
        result = await downloader.download(paper)
        assert result is None
        assert queue_path.exists()
        content = queue_path.read_text(encoding="utf-8-sig")
        assert "中文测试文献" in content
        assert "manual_or_authenticated_access_required" in content
    finally:
        await downloader.close()
        cache.close()
        Path(db_path).unlink(missing_ok=True)
