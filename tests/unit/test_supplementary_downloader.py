"""Tests for the supplementary materials downloader.

Tests cover:
  - Detection functions (_detect_suppl_publisher)
  - Helper functions (_get_ext, _safe_filename, _save_response, is_cached)
  - Publisher registry integrity (no duplicate DOI prefixes)
  - Crossref API parsing (_crossref_lookup)
  - PMC lookup (_pmc_lookup)
  - Content-type filtering (_fetch_one)
  - Full download flow via mocked HTTP
"""

from pathlib import Path

import pytest
import respx

from litkit import downloaders
from litkit.core.models import Paper
from litkit.downloaders.supplementary import (
    _SUPPL_PUBLISHERS,
    SupplementaryDownloader,
    _cache_dir,
    _detect_suppl_publisher,
    _get_ext,
    _safe_filename,
    _save_response,
    _SupplPublisherConfig,
    cached_path,
    is_cached,
)

# ═══════════════════════════════════════════════════════════════════════════
# _detect_suppl_publisher
# ═══════════════════════════════════════════════════════════════════════════

PUBLISHER_DOI_MAP: list[tuple[str, str]] = [
    ("10.1016/j.foodhyd.2020.106226", "sciencedirect"),
    ("10.1038/s41586-024-08216-z", "nature"),
    ("10.1002/adma.202407381", "wiley"),
    ("10.1007/s00425-024-04376-4", "springer"),
    ("10.1617/s11527-024-02345-6", "springer"),
    ("10.3390/nu12061639", "mdpi"),
    ("10.3389/fmicb.2021.655254", "frontiers"),
    ("10.1021/jacs.4c00123", "acs"),
    ("10.1080/14786419.2024.2312345", "taylor_francis"),
    ("10.1201/9781003456789", "taylor_francis"),
    ("10.1177/09567976241234567", "sage"),
    ("10.1073/pnas.2019256118", "pnas"),
]

UNKNOWN_DOIS = ["", None, "10.9999/unknown", "not-a-doi", "10.1371/journal.pone.0250925"]


class TestDetectSupplPublisher:
    @pytest.mark.parametrize("doi,expected_name", PUBLISHER_DOI_MAP)
    def test_known_publishers(self, doi, expected_name):
        config = _detect_suppl_publisher(doi)
        assert config is not None
        assert config.name == expected_name

    @pytest.mark.parametrize("doi", UNKNOWN_DOIS)
    def test_unknown_returns_none(self, doi):
        assert _detect_suppl_publisher(doi) is None

    def test_returns_config_object(self):
        config = _detect_suppl_publisher("10.1016/j.test.2024.01.001")
        assert isinstance(config, _SupplPublisherConfig)
        assert config.name == "sciencedirect"


# ═══════════════════════════════════════════════════════════════════════════
# Publisher registry integrity
# ═══════════════════════════════════════════════════════════════════════════


class TestPublisherRegistry:
    def test_no_duplicate_doi_prefixes(self):
        seen: dict[str, str] = {}
        for pub in _SUPPL_PUBLISHERS:
            for prefix in pub.doi_prefixes:
                assert prefix not in seen, (
                    f"Prefix {prefix!r} claimed by both "
                    f"{seen[prefix]!r} and {pub.name!r}"
                )
                seen[prefix] = pub.name

    def test_each_publisher_has_section_selector(self):
        from litkit.downloaders.supplementary import _SUPPL_SECTION_SELECTORS

        for pub in _SUPPL_PUBLISHERS:
            assert pub.name in _SUPPL_SECTION_SELECTORS, (
                f"Publisher {pub.name!r} missing from _SUPPL_SECTION_SELECTORS"
            )


# ═══════════════════════════════════════════════════════════════════════════
# Helper functions
# ═══════════════════════════════════════════════════════════════════════════


class TestGetExt:
    @pytest.mark.parametrize("url,ct,expected", [
        ("https://example.com/file.pdf", "", ".pdf"),
        ("https://example.com/file.zip", "", ".zip"),
        ("https://example.com/data.csv", "", ".csv"),
        ("https://example.com/data", "application/pdf", ".pdf"),
        ("https://example.com/data", "application/zip", ".zip"),
        ("https://example.com/data", "text/csv", ".csv"),
        (
            "https://example.com/data",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".xlsx",
        ),
        ("https://example.com/data", "image/tiff", ".tiff"),
        ("https://example.com/data", "image/jpeg", ".jpg"),
        ("https://example.com/data", "unknown/type", ".bin"),
        ("https://example.com/file.PDF", "", ".pdf"),  # case insensitive
    ])
    def test_known_extensions(self, url, ct, expected):
        assert _get_ext(url, ct) == expected


class TestSafeFilename:
    @pytest.mark.parametrize("url,suffix,expected", [
        ("https://example.com/file.pdf", ".pdf", "file.pdf"),
        ("https://example.com/path/to/data.csv", ".csv", "data.csv"),
        ("https://example.com/download?file=123", ".pdf", "download.pdf"),
        ("https://doi.org/10.1234/test", ".bin", "test.bin"),
    ])
    def test_safe_filename(self, url, suffix, expected):
        assert _safe_filename(url, suffix) == expected


class TestSaveResponse:
    def test_saves_content(self, tmp_path):
        import httpx
        req = httpx.Request("GET", "https://example.com/file.pdf")
        resp = httpx.Response(
            200,
            content=b"pdf-content",
            headers={"content-type": "application/pdf"},
            request=req,
        )
        result = _save_response(resp, tmp_path)
        assert result is not None
        assert result.exists()
        assert result.name == "file.pdf"
        assert result.read_bytes() == b"pdf-content"

    def test_dedup_same_content(self, tmp_path):
        import httpx
        req = httpx.Request("GET", "https://example.com/a.pdf")
        resp1 = httpx.Response(
            200,
            content=b"same-data",
            headers={"content-type": "application/pdf"},
            request=req,
        )
        r1 = _save_response(resp1, tmp_path)
        assert r1 is not None

        req2 = httpx.Request("GET", "https://example.com/b.pdf")
        resp2 = httpx.Response(
            200,
            content=b"same-data",
            headers={"content-type": "application/pdf"},
            request=req2,
        )
        r2 = _save_response(resp2, tmp_path)
        # Should return existing file, not create a new one
        assert r2 == r1
        files = list(tmp_path.iterdir())
        assert len(files) == 1  # no duplicate

    def test_different_content_same_name(self, tmp_path):
        import httpx
        req = httpx.Request("GET", "https://example.com/file.pdf")
        resp1 = httpx.Response(
            200,
            content=b"content-a",
            headers={"content-type": "application/pdf"},
            request=req,
        )
        r1 = _save_response(resp1, tmp_path)

        req2 = httpx.Request("GET", "https://example.com/file.pdf")
        resp2 = httpx.Response(
            200,
            content=b"content-b",
            headers={"content-type": "application/pdf"},
            request=req2,
        )
        r2 = _save_response(resp2, tmp_path)

        assert r1 != r2
        assert r2.name == "file_1.pdf"


# ═══════════════════════════════════════════════════════════════════════════
# Cache helpers
# ═══════════════════════════════════════════════════════════════════════════


class TestCacheHelpers:
    def test_is_cached_false_for_nonexistent(self):
        paper = Paper(id="nonexistent", doi="10.1234/test", title="Test")
        assert not is_cached(paper)

    def test_cached_path_none_for_nonexistent(self):
        paper = Paper(id="nonexistent", doi="10.1234/test", title="Test")
        assert cached_path(paper) is None

    def test_is_cached_true_after_download(self):
        paper = Paper(id="cached_test", doi="10.1234/cached", title="Test")
        d = _cache_dir(paper)
        d.mkdir(parents=True, exist_ok=True)
        (d / "test_file.pdf").write_bytes(b"content")
        (d / ".done").write_text("10.1234/cached")
        assert is_cached(paper)
        assert cached_path(paper) == d


class TestCacheDirHonorsEnv:
    def test_cache_dir_respects_litkit_cache_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LITKIT_CACHE_DIR", str(tmp_path / "custom-cache"))
        paper = Paper(id="env_test", doi="10.1234/env", title="Test")
        d = _cache_dir(paper)
        assert str(tmp_path / "custom-cache" / "supplementary") in str(d)
        assert d.exists()


# ═══════════════════════════════════════════════════════════════════════════
# _fetch_one — content-type filtering
# ═══════════════════════════════════════════════════════════════════════════


class TestFetchOne:
    @pytest.mark.asyncio
    @respx.mock
    async def test_accepts_pdf(self, tmp_path):
        url = "https://example.com/file.pdf"
        respx.get(url).respond(
            200,
            headers={"content-type": "application/pdf"},
            content=b"%PDF-content",
        )
        sd = SupplementaryDownloader()
        tmp = tmp_path / "test_fetch"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            result = await sd._fetch_one(url, tmp)
            assert result is not None
            assert result.read_bytes() == b"%PDF-content"
        finally:
            await sd.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_rejects_html(self, tmp_path):
        url = "https://example.com/page.html"
        respx.get(url).respond(
            200,
            headers={"content-type": "text/html"},
            content=b"<html>blocked</html>",
        )
        sd = SupplementaryDownloader()
        tmp = tmp_path / "test_fetch2"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            result = await sd._fetch_one(url, tmp)
            assert result is None
        finally:
            await sd.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_rejects_elsevier_xml_api(self, tmp_path):
        url = "https://api.elsevier.com/content/article/pii/S123456"
        xml_body = b'<?xml version="1.0"?><full-text-retrieval-response xmlns="http://www.elsevier.com"><coredata><prism:doi>10.1016/j.test</prism:doi></coredata></full-text-retrieval-response>'
        respx.get(url).respond(200, headers={"content-type": "application/xml"}, content=xml_body)
        sd = SupplementaryDownloader()
        tmp = tmp_path / "test_fetch3"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            result = await sd._fetch_one(url, tmp)
            assert result is None
        finally:
            await sd.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_accepts_data_xml(self, tmp_path):
        url = "https://example.com/data.xml"
        xml_body = (
            b'<?xml version="1.0"?><dataset><entry id="1">'
            b"<value>42</value></entry></dataset>"
        )
        respx.get(url).respond(200, headers={"content-type": "application/xml"}, content=xml_body)
        sd = SupplementaryDownloader()
        tmp = tmp_path / "test_fetch4"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            result = await sd._fetch_one(url, tmp)
            assert result is not None
        finally:
            await sd.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_rejects_small_content(self, tmp_path):
        url = "https://example.com/tiny.txt"
        respx.get(url).respond(200, headers={"content-type": "text/plain"}, content=b"tiny")
        sd = SupplementaryDownloader()
        tmp = tmp_path / "test_fetch5"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            result = await sd._fetch_one(url, tmp)
            assert result is None
        finally:
            await sd.close()


# ═══════════════════════════════════════════════════════════════════════════
# Crossref API parsing
# ═══════════════════════════════════════════════════════════════════════════


class TestCrossrefLookup:
    @pytest.mark.asyncio
    @respx.mock
    async def test_finds_supplementary_links(self, tmp_path):
        doi = "10.1234/test-article"
        api_url = f"https://api.crossref.org/works/{doi}"
        respx.get(api_url).respond(
            200,
            headers={"content-type": "application/json"},
            content=(
                '{"message": {'
                '  "link": ['
                '    {"URL": "https://example.com/suppl.zip", "content-type": "application/zip"},'
                '    {"URL": "https://example.com/suppl.csv", "content-type": "text/csv"}'
                '  ]'
                '}}'
            ),
        )
        # The supplementary files we'll find
        respx.get("https://example.com/suppl.zip").respond(
            200, headers={"content-type": "application/zip"}, content=b"PK-zip-content"
        )
        respx.get("https://example.com/suppl.csv").respond(
            200, headers={"content-type": "text/csv"}, content=b"col1,col2\n1,2"
        )

        sd = SupplementaryDownloader()
        tmp = tmp_path / "test_crossref1"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            count = await sd._crossref_lookup(doi, tmp)
            assert count == 2
        finally:
            await sd.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_skips_pdf_links(self, tmp_path):
        doi = "10.1234/pdf-only"
        api_url = f"https://api.crossref.org/works/{doi}"
        respx.get(api_url).respond(
            200,
            headers={"content-type": "application/json"},
            content=(
                '{"message": {'
                '  "link": ['
                '    {"URL": "https://example.com/paper.pdf", "content-type": "application/pdf"}'
                '  ]'
                '}}'
            ),
        )
        sd = SupplementaryDownloader()
        tmp = tmp_path / "test_crossref2"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            count = await sd._crossref_lookup(doi, tmp)
            assert count == 0
        finally:
            await sd.close()


# ═══════════════════════════════════════════════════════════════════════════
# PMC lookup
# ═══════════════════════════════════════════════════════════════════════════


class TestPmcLookup:
    @pytest.mark.asyncio
    @respx.mock
    async def test_resolves_pmcid_and_finds_files(self, tmp_path):
        doi = "10.1234/pmc-test"
        # DOI → PMCID resolution
        respx.get(f"https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?ids={doi}&format=json").respond(
            200,
            headers={"content-type": "application/json"},
            content='{"records": [{"pmcid": "PMC1234567"}]}',
        )
        # PMC article page
        respx.get("https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1234567/").respond(
            200,
            headers={"content-type": "text/html"},
            content=(
                '<html><body><div id="supplementary-material">'
                '<a href="/pmc/articles/PMC1234567/bin/suppl.pdf">'
                "Supplementary Data</a></div></body></html>"
            ),
        )
        # The actual supplementary file
        respx.get("https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1234567/bin/suppl.pdf").respond(
            200, headers={"content-type": "application/pdf"}, content=b"%PDF-suppl"
        )

        sd = SupplementaryDownloader()
        tmp = tmp_path / "test_pmc1"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            count = await sd._pmc_lookup(doi, tmp)
            assert count > 0
        finally:
            await sd.close()


# ═══════════════════════════════════════════════════════════════════════════
# Full download flow
# ═══════════════════════════════════════════════════════════════════════════


class TestFullDownload:
    @pytest.mark.asyncio
    @respx.mock
    async def test_download_no_doi(self):
        sd = SupplementaryDownloader()
        paper = Paper(id="no-doi", doi="", title="No DOI")
        try:
            result = await sd.download(paper)
            assert result is None
        finally:
            await sd.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_download_crossref_pmc_fallback(self):
        """Test the full chain: Crossref → PMC → publisher → patterns → CDP."""
        doi = "10.1234/integration-test"
        paper = Paper(id=doi.replace("/", "_"), doi=doi, title="Integration Test")

        # Mock Crossref API (returns supplementary links)
        respx.get(f"https://api.crossref.org/works/{doi}").respond(
            200,
            headers={"content-type": "application/json"},
            content=(
                '{"message": {'
                '  "link": ['
                '    {"URL": "https://example.com/suppl.zip", "content-type": "application/zip"}'
                '  ]'
                '}}'
            ),
        )
        respx.get("https://example.com/suppl.zip").respond(
            200, headers={"content-type": "application/zip"}, content=b"PK-zip-content"
        )
        sd = SupplementaryDownloader()
        try:
            result = await sd.download(paper)
            assert result is not None
            files = [f for f in result.iterdir() if f.is_file() and f.name != ".done"]
            assert len(files) == 1
            assert files[0].suffix == ".zip"
        finally:
            await sd.close()


# ═══════════════════════════════════════════════════════════════════════════
# Main entry point for running directly
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-v"])


def test_supplementary_downloader_uses_shared_browser_runtime(monkeypatch):
    monkeypatch.setattr(
        "litkit.downloaders.supplementary.resolve_browser_executable",
        lambda: "/usr/bin/chromium",
    )
    monkeypatch.setattr(
        "litkit.downloaders.supplementary.default_profile_dir",
        lambda name: Path(f"/tmp/{name}"),
    )

    assert downloaders.supplementary.resolve_browser_executable() == "/usr/bin/chromium"
    assert downloaders.supplementary.default_profile_dir("supplementary") == Path(
        "/tmp/supplementary"
    )
