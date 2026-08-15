"""Tests for institutional downloader — publisher detection, login heuristics, and integration.

Notable properties tested here:

* ``_detect_publisher`` maps every recognised DOI prefix to the correct
  :class:`PublisherConfig` and returns ``None`` for unknown prefixes.
* ``_is_login_page`` uses a three-tier size heuristic so that large article
  pages (e.g. Nature 608 KB) are *not* treated as login pages just because
  their navigation bar contains "sign in".
* Publisher registry integrity — no duplicate DOI prefixes.
"""


from pathlib import Path

import pytest

from litkit import downloaders
from litkit.config import EnvConfig
from litkit.core.cache import MetadataCache
from litkit.core.models import Paper
from litkit.downloaders.institutional import (
    _PUBLISHERS,
    PublisherConfig,
    _chrome_entry_url,
    _detect_publisher,
    _is_login_page,
    _is_sciencedirect_article_url,
    _is_sciencedirect_asset_pdf_url,
    _mdpi_parts,
    _pdf_byte_count,
    _rendered_pdf_looks_like_challenge,
    _should_use_print_to_pdf_fallback,
    _text_looks_like_article_page,
    _text_looks_like_full_article,
    _text_mentions_paper,
)

# ---------------------------------------------------------------------------
# _detect_publisher
# ---------------------------------------------------------------------------

PUBLISHER_DOI_MAP: list[tuple[str, str]] = [
    ("10.1016/j.ecolmodel.2024.110850", "sciencedirect"),
    ("10.1038/s41586-024-08216-z", "nature"),
    ("10.1002/adma.202407381", "wiley"),
    ("10.1111/1750-3841.71116", "wiley"),
    ("10.1029/2003eo460002", "wiley"),
    ("10.1190/1.3059384", "seg"),
    ("10.1007/s00425-024-04376-4", "springer"),
    ("10.1617/s11527-024-02345-6", "springer"),  # second prefix
    ("10.1109/TRO.2024.3354321", "ieee"),
    ("10.1021/jacs.4c00123", "acs"),
    ("10.1039/D4CP00123A", "rsc"),
    ("10.1080/14786419.2024.2312345", "taylor_francis"),
    ("10.1201/9781003456789", "taylor_francis"),  # second prefix
    ("10.1177/09567976241234567", "sage"),
    ("10.1515/9783110987654", "degruyter"),
    ("10.1785/bssa0880061484", "geoscienceworld"),
    ("10.2139/ssrn.4719853", "ssrn"),
]

UNKNOWN_DOIS = [
    "",
    None,
    "10.9999/unknown",
    "not-a-doi",
]


class TestDetectPublisher:
    @pytest.mark.parametrize("doi,expected_name", PUBLISHER_DOI_MAP)
    def test_known_publishers(self, doi, expected_name):
        config = _detect_publisher(doi)
        assert config is not None
        assert config.name == expected_name

    @pytest.mark.parametrize("doi", UNKNOWN_DOIS)
    def test_unknown_returns_none(self, doi):
        assert _detect_publisher(doi) is None

    def returned_config_is_frozen(self):
        config = _detect_publisher("10.1016/j.test.2024.01.001")
        assert isinstance(config, PublisherConfig)
        with pytest.raises(AttributeError):
            config.name = "hacked"  # type: ignore[misc]


def test_chrome_entry_url_prefers_ieee_document_page():
    paper = Paper(doi="10.1109/iecon.2016.7792968", title="test")
    publisher = _detect_publisher(paper.doi)
    assert publisher is not None
    assert _chrome_entry_url(paper, publisher) == "https://ieeexplore.ieee.org/document/7792968/"


def test_chrome_entry_url_uses_source_url_when_not_doi():
    paper = Paper(
        doi="10.1016/j.foodchem.2023.137592",
        title="test",
        source_url="https://www.sciencedirect.com/science/article/pii/S0308814623031234",
    )
    publisher = _detect_publisher(paper.doi)
    assert publisher is not None
    assert _chrome_entry_url(paper, publisher) == paper.source_url


def test_chrome_entry_url_ignores_aggregator_source_url_for_sciencedirect():
    paper = Paper(
        doi="10.1016/j.foodchem.2023.137592",
        title="test",
        source_url="https://pubmed.ncbi.nlm.nih.gov/37778267/",
    )
    publisher = _detect_publisher(paper.doi)
    assert publisher is not None
    assert _chrome_entry_url(paper, publisher) == "https://doi.org/10.1016/j.foodchem.2023.137592"


def test_chrome_entry_url_uses_agu_wiley_landing_page():
    paper = Paper(doi="10.1029/2003eo460002", title="test")
    publisher = _detect_publisher(paper.doi)
    assert publisher is not None
    assert _chrome_entry_url(paper, publisher) == (
        "https://agupubs.onlinelibrary.wiley.com/doi/10.1029/2003EO460002"
    )


# ---------------------------------------------------------------------------
# Publisher registry integrity
# ---------------------------------------------------------------------------


class TestPublisherRegistry:
    def test_no_duplicate_doi_prefixes(self):
        seen: dict[str, str] = {}
        for pub in _PUBLISHERS:
            for prefix in pub.doi_prefixes:
                assert prefix not in seen, (
                    f"Duplicate DOI prefix {prefix!r}: used in {pub.name!r} and {seen[prefix]!r}"
                )
                seen[prefix] = pub.name

    def test_all_publishers_have_names(self):
        for pub in _PUBLISHERS:
            assert pub.name, "Every PublisherConfig must have a non-empty name"
            assert pub.doi_prefixes, f"{pub.name} must have at least one DOI prefix"


# ---------------------------------------------------------------------------
# _is_login_page  (three-tier size heuristic)
# ---------------------------------------------------------------------------
#
# NOTE: Tests build HTML strings at runtime (not via parametrize) because
# the large page-size strings (up to 200 KB) produce unreadable pytest
# output when embedded as parametrize values.


def _build_page(keyword: str, size_bytes: int, tag: str = "") -> str:
    """Build an HTML string of approximately *size_bytes*."""
    prefix = f"<html>{tag}{keyword}"
    padding = max(0, size_bytes - len(prefix) - len("</html>"))
    return prefix + "x" * padding + "</html>"


class TestIsLoginPage:
    def test_tiny_always_blocked(self):
        assert _is_login_page("<html>block</html>") is True

    def test_tiny_just_under_2k(self):
        assert _is_login_page("x" * 1999) is True

    def test_medium_weak_signin(self):
        html = _build_page("sign in", 22_000)
        assert _is_login_page(html) is True

    def test_medium_weak_login(self):
        html = _build_page("login", 32_000)
        assert _is_login_page(html) is True

    def test_medium_strong_institutional(self):
        html = _build_page("institutional login", 27_000)
        assert _is_login_page(html) is True

    def test_medium_clean(self):
        html = _build_page("article content here", 27_000)
        assert _is_login_page(html) is False

    def test_large_signin_nav_not_blocked(self):
        """WEAK keyword in nav on large page -> not a login page."""
        html = _build_page("sign in", 62_000, tag="<nav>")
        assert _is_login_page(html) is False

    def test_large_subscribe_nav_not_blocked(self):
        html = _build_page("subscribe", 102_000, tag="<footer>")
        assert _is_login_page(html) is False

    def test_large_strong_institutional_blocked(self):
        html = _build_page("institutional login", 102_000)
        assert _is_login_page(html) is True

    def test_large_strong_access_denied_blocked(self):
        html = _build_page("access denied", 82_000)
        assert _is_login_page(html) is True

    def test_large_strong_purchase_blocked(self):
        html = _build_page("purchase this article", 202_000)
        assert _is_login_page(html) is True

    def test_large_strong_sign_in_to_view_blocked(self):
        html = _build_page("sign in to view", 72_000)
        assert _is_login_page(html) is True

    def test_large_clean_not_blocked(self):
        html = _build_page("article with no login keywords", 102_000)
        assert _is_login_page(html) is False

    def test_empty_html(self):
        assert _is_login_page("") is True

    def test_none_html(self):
        assert _is_login_page(None) is True  # type: ignore[arg-type]


def test_pdf_byte_count_uses_content_length():
    assert _pdf_byte_count(b"%PDF-test-content") == 17


def test_mdpi_parts_derives_cdn_slug():
    assert _mdpi_parts("10.3390/nu14030588") == ("nutrients", "nutrients-14-00588")
    assert _mdpi_parts("10.3390/polym15010001") == ("polymers", "polymers-15-00001")
    assert _mdpi_parts("10.3390/foods13010002") == ("foods", "foods-13-00002")
    assert _mdpi_parts("10.1016/j.foodres.2025.117135") is None
    assert _mdpi_parts("10.3390/notamatching") is None


def test_sciencedirect_asset_pdf_url_detection():
    assert _is_sciencedirect_asset_pdf_url(
        "https://pdf.sciencedirectassets.com/123456/1-s2.0-S0963996925000012-main.pdf"
    )
    assert not _is_sciencedirect_asset_pdf_url(
        "https://www.sciencedirect.com/science/article/pii/S0963996925000012/pdfft"
    )


def test_sciencedirect_article_url_detection_handles_proxy_hosts():
    assert _is_sciencedirect_article_url(
        "https://www.sciencedirect.com/science/article/pii/S0963996925000012?via=ihub"
    )
    assert _is_sciencedirect_article_url(
        "https://www-sciencedirect-com.ezproxy.lib.szu.edu.cn/science/article/pii/"
        "S0963996925000012?via%3Dihub"
    )
    assert not _is_sciencedirect_article_url(
        "https://linkinghub-elsevier-com.ezproxy.lib.szu.edu.cn/retrieve/pii/S0963996925000012"
    )


def test_sciencedirect_skips_browser_rendered_print_to_pdf_fallback():
    sciencedirect = _detect_publisher("10.1016/j.foodres.2025.116293")
    wiley = _detect_publisher("10.1111/1750-3841.71116")

    assert sciencedirect is not None
    assert wiley is not None
    assert _should_use_print_to_pdf_fallback(sciencedirect) is False
    assert _should_use_print_to_pdf_fallback(wiley) is True


def test_institutional_downloader_uses_shared_browser_runtime(monkeypatch):
    monkeypatch.setattr(
        "litkit.downloaders.institutional.resolve_browser_executable",
        lambda: "/usr/bin/google-chrome",
    )
    monkeypatch.setattr(
        "litkit.downloaders.institutional.default_profile_dir",
        lambda name: Path(f"/tmp/{name}"),
    )

    assert downloaders.institutional.resolve_browser_executable() == "/usr/bin/google-chrome"
    assert downloaders.institutional.default_profile_dir("institutional") == Path(
        "/tmp/institutional"
    )


def test_browser_proxy_url_rewrites_szu_ezproxy_login_prefix(tmp_path: Path):
    downloader = downloaders.institutional.InstitutionalDownloader(
        MetadataCache(tmp_path / "cache.db"),
        EnvConfig(institutional_proxy="http://ezproxy.lib.szu.edu.cn/login?url="),
    )

    assert downloader._browser_proxy_url("https://ieeexplore.ieee.org/document/8217285/") == (
        "https://ieeexplore-ieee-org.ezproxy.lib.szu.edu.cn/document/8217285/"
    )


def test_browser_target_candidates_prefer_proxy_for_sciencedirect_when_available(tmp_path: Path):
    downloader = downloaders.institutional.InstitutionalDownloader(
        MetadataCache(tmp_path / "cache.db"),
        EnvConfig(
            institutional_proxy="http://ezproxy.lib.szu.edu.cn/login?url=",
            institutional_direct=True,
        ),
    )
    publisher = _detect_publisher("10.1016/j.foodchem.2023.137592")

    assert publisher is not None
    assert downloader._browser_target_candidates(
        "https://www.sciencedirect.com/science/article/pii/S0308814623031234",
        publisher,
    ) == [
        "https://www-sciencedirect-com.ezproxy.lib.szu.edu.cn/science/article/pii/S0308814623031234",
        "https://www.sciencedirect.com/science/article/pii/S0308814623031234",
    ]

    downloader._cache.close()


def test_browser_target_candidates_prefer_proxy_for_wiley_when_available(tmp_path: Path):
    downloader = downloaders.institutional.InstitutionalDownloader(
        MetadataCache(tmp_path / "cache.db"),
        EnvConfig(
            institutional_proxy="http://ezproxy.lib.szu.edu.cn/login?url=",
            institutional_direct=True,
        ),
    )
    publisher = _detect_publisher("10.1111/jpn.70074")

    assert publisher is not None
    assert downloader._browser_target_candidates(
        "https://onlinelibrary.wiley.com/doi/10.1111/jpn.70074",
        publisher,
    ) == [
        "https://onlinelibrary-wiley-com.ezproxy.lib.szu.edu.cn/doi/10.1111/jpn.70074",
        "https://onlinelibrary.wiley.com/doi/10.1111/jpn.70074",
    ]

    downloader._cache.close()


def test_full_article_heuristic_requires_real_section_markers():
    full_text = (
        "Abstract\n"
        "Introduction\n"
        + ("body text " * 2000)
        + "\nMaterials and methods\nResults and discussion\nConclusion\nReferences\n"
    )
    short_text = "Abstract\nIntroduction\nConclusion\n"

    assert _text_looks_like_full_article(full_text) is True
    assert _text_looks_like_full_article(short_text) is False


def test_full_article_heuristic_accepts_reviews_with_few_markers():
    """Long review-style pages without explicit intro/methods headings must
    still qualify for the printToPDF fallback (jfp/foodchem regression)."""
    review_text = (
        "Abstract\n"
        + ("body text " * 8000)  # > 30k chars
        + "\nConclusion\nReferences\n"
    )
    assert _text_looks_like_full_article(review_text) is True


def test_full_article_heuristic_rejects_short_text_even_with_markers():
    """Short pages (abstract-only / in-press) must never qualify."""
    abstract_only = (
        "Abstract\nBackground\nObjective\n"
        + ("body text " * 100)  # ~1k chars
        + "\nResults\nConclusions\nFunding\n"
    )
    assert _text_looks_like_full_article(abstract_only) is False


def test_text_mentions_paper_requires_distinctive_title_overlap():
    paper = Paper(
        doi="10.1111/jpn.70074",
        title="Beyond Immunity Functional Outcomes of Dietary Yeast and Seaweed beta Glucans",
    )
    article_text = (
        "Beyond Immunity Functional Outcomes of Dietary Yeast and Seaweed beta Glucans "
        "in adult canine nutrition. Abstract. Results. References."
    )
    challenge_text = "Verify you are human before continuing to Wiley Online Library."

    assert _text_mentions_paper(article_text, paper) is True
    assert _text_mentions_paper(challenge_text, paper) is False


def test_article_page_heuristic_rejects_challenge_text():
    paper = Paper(
        doi="10.1111/jpn.70074",
        title="Beyond Immunity Functional Outcomes of Dietary Yeast and Seaweed beta Glucans",
    )
    article_text = (
        "Beyond Immunity Functional Outcomes of Dietary Yeast and Seaweed beta Glucans\n"
        + ("body text " * 250)
        + "\nAbstract\nIntroduction\nResults\nReferences\n"
    )
    challenge_text = (
        "Verify you are human\n"
        + ("Cloudflare Turnstile " * 200)
        + "\nChecking your browser before accessing Wiley Online Library.\n"
    )

    assert _text_looks_like_article_page(article_text, paper) is True
    assert _text_looks_like_article_page(challenge_text, paper) is False


def test_rendered_pdf_challenge_detection():
    suspicious_pdf = (
        b"%PDF-1.4\n"
        b"https://www.cloudflare.com/products/turnstile/\n"
        b"https://challenges.cloudflare.com/cdn-cgi/challenge-platform/help\n"
    )
    article_pdf = b"%PDF-1.4\nPilot scale production and structural characterization\nReferences\n"

    assert _rendered_pdf_looks_like_challenge(suspicious_pdf) is True
    assert _rendered_pdf_looks_like_challenge(article_pdf) is False


@pytest.mark.asyncio
async def test_browser_entry_url_uses_cached_resolution(tmp_path):
    cache = MetadataCache(tmp_path / "cache.db")
    cache.put_doi_resolution("10.2139/ssrn.4719853", "https://www.ssrn.com/abstract=4719853")
    downloader = downloaders.institutional.InstitutionalDownloader(cache, EnvConfig())
    paper = Paper(doi="10.2139/ssrn.4719853", title="Test")
    publisher = _detect_publisher(paper.doi)

    assert publisher is not None
    assert await downloader._browser_entry_url(paper, publisher) == (
        "https://www.ssrn.com/abstract=4719853"
    )

    await downloader.close()
    cache.close()
