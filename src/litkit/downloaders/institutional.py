"""Download PDFs using institutional access via EZProxy or on-campus IP.

Two modes:

1. **Proxy mode** (recommended for off-campus): Set ``INSTITUTIONAL_PROXY``
   in ``.env`` to your university's EZProxy prefix.  All requests are
   routed through the proxy, which handles authentication.

   .. code-block:: bash

       INSTITUTIONAL_PROXY=https://ezproxy.youruni.edu/login?url=

   If your EZProxy requires a session cookie (most do), export cookies
   from your browser after logging in and point to the file:

   .. code-block:: bash

       INSTITUTIONAL_COOKIE_FILE=/path/to/cookies.txt

2. **Direct mode** (on-campus / VPN): Set ``INSTITUTIONAL_DIRECT=true``
   and leave the proxy blank.  Requests go directly to publisher PDF URLs
   and rely on IP-based authentication.

Strategy order for each paper:

1. Known direct-PDF URL patterns for major publishers (Springer, Wiley,
   Taylor & Francis, Sage) — through proxy if configured.
2. The DOI URL (``https://doi.org/{doi}``) itself.
3. If a response is HTML, parse for ``citation_pdf_url`` meta tag or
   ``.pdf`` links and follow the first match.
4. **ScienceDirect Chrome CDP fallback** — for Elsevier articles
   (DOI prefix ``10.1016/``) blocked by DataDome at the S3 CDN.
   Launches real Chrome via remote debugging, connects via Playwright
   CDP, and downloads the PDF through the browser (bypasses DataDome).
   Falls back gracefully if Playwright or Chrome is unavailable.

**Note:** Institutional is intentionally the last downloader in the chain
(behind SciHub, LibGen, Anna's Archive) because EZProxy has a 50 MB daily
download limit — shadow libraries run first to conserve quota.
"""

from __future__ import annotations

import asyncio
import contextlib
import http.cookiejar as cookiejar
import logging
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import httpx

from litkit.browser_runtime import (
    browser_launch_args,
    default_profile_dir,
    kill_process_tree,
    resolve_browser_executable,
    spawn_process_kwargs,
)
from litkit.core.models import Paper
from litkit.core.ratelimit import bucket_for
from litkit.downloaders.base import Downloader

logger = logging.getLogger(__name__)


def _pdf_byte_count(data: bytes) -> int:
    """Return the persisted PDF byte count for logging and verification."""
    return len(data)


def _mdpi_parts(doi: str) -> tuple[str, str] | None:
    """Return (journal_slug, article_stem) for an MDPI DOI, else None.

    MDPI article DOIs encode volume, issue and article number in a
    fixed-width digit suffix after a journal abbreviation, e.g.
    10.3390/nu14030588 -> nu (vol 14, issue 03, article 588)
    -> CDN slug "nutrients", article stem "nutrients-14-00588".
    The journal mapping is shared with publisher_direct.
    """
    from litkit.downloaders.publisher_direct import (
        _MDPI_JOURNAL_NAMES,
        _mdpi_res_urls,
    )

    urls = _mdpi_res_urls(doi)
    if not urls:
        return None
    stem = urls[0].rsplit("/", 1)[-1][:-4]
    name = stem.rsplit("-", 2)[0]
    return (_MDPI_JOURNAL_NAMES.get(name, name), stem)


# ---------------------------------------------------------------------------
# Optional Playwright import (Chrome CDP fallback)
# ---------------------------------------------------------------------------
try:
    from playwright.async_api import async_playwright

    HAS_PLAYWRIGHT = True
except ImportError:  # pragma: no cover
    HAS_PLAYWRIGHT = False

# ---------------------------------------------------------------------------
# Known publisher direct-PDF URL patterns.
# Each {doi} placeholder is replaced with the paper's DOI.
# ---------------------------------------------------------------------------
_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

_PUBLISHER_PDF_PATTERNS: list[str] = [
    "https://link.springer.com/content/pdf/{doi}.pdf",  # Springer
    "https://onlinelibrary.wiley.com/doi/pdf/{doi}",  # Wiley
    "https://www.tandfonline.com/doi/pdf/{doi}",  # Taylor & Francis
    "https://journals.sagepub.com/doi/pdf/{doi}",  # Sage
    # Nature journals — DOI path suffix + .pdf
    # e.g. 10.1038/s41586-024-07155-0 → articles/s41586-024-07155-0.pdf
    "https://www.nature.com/articles/{doi_path}.pdf",
    # Science (AAAS)
    "https://www.science.org/doi/pdf/{doi}",
    # MDPI (open access) - www.mdpi.com 403s non-browser clients,
    # so try the predictable mdpi-res.com CDN link first.
    "https://mdpi-res.com/d_attachment/{mdpi_abbr}/{mdpi_stem}/article_deploy/{mdpi_stem}.pdf",
    "https://www.mdpi.com/{doi_path}/pdf",
    # Frontiers (open access)
    "https://www.frontiersin.org/journals/{doi_path}/pdf",
    # ACS
    "https://pubs.acs.org/doi/pdf/{doi}",
]

# ---------------------------------------------------------------------------
# HTML parsing helpers
# ---------------------------------------------------------------------------
_META_PDF_RE = re.compile(
    r'<meta\s[^>]*name\s*=\s*["\']citation_pdf_url["\'][^>]*'
    r'content\s*=\s*["\'](?P<url>[^"\']+)["\']',
    re.IGNORECASE,
)

_A_PDF_RE = re.compile(
    r'<a\s[^>]*href\s*=\s*["\'](?P<url>[^"\']+\.pdf[^"\']*)["\']',
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# EZProxy tracking page detection
# ---------------------------------------------------------------------------
_EZPROXY_TRACKING_RE = re.compile(
    r"""location\.href\s*=\s*["'](?P<url>[^"']+)["']""",
)


# ---------------------------------------------------------------------------
# ScienceDirect / DataDome / TDM block detection
# ---------------------------------------------------------------------------
_SD_DOI_PREFIX = "10.1016/"
_TDM_KEYWORDS = (
    "tdm-reservation",
    "datadome",
    "just a moment",
    "security verification",
    "cdn-cgi/challenge-platform",
    "turnstile",
    "请稍候",
)
_RENDERED_PDF_CHALLENGE_MARKERS = (
    b"cloudflare",
    b"challenge-platform",
    b"turnstile",
    b"captcha",
    b"verify you are human",
    b"checking your browser",
    b"security verification",
    b"attention required",
)

_LIGHTWEIGHT_ARTICLE_MARKERS = (
    "abstract",
    "introduction",
    "materials and methods",
    "results",
    "discussion",
    "conclusion",
    "references",
)

_TITLE_STOPWORDS = {
    "about",
    "adult",
    "against",
    "among",
    "assessment",
    "beyond",
    "between",
    "effects",
    "from",
    "into",
    "nutrition",
    "outcomes",
    "performance",
    "pilot",
    "production",
    "randomized",
    "study",
    "supplementation",
    "through",
    "using",
    "with",
}


def _is_science_direct(doi: str) -> bool:
    """Return True if the DOI belongs to a ScienceDirect article."""
    return doi.lower().startswith(_SD_DOI_PREFIX) if doi else False


def _is_sciencedirect_asset_pdf_url(url: str) -> bool:
    """Return True when *url* is ScienceDirect's temporary PDF asset URL."""
    parsed = urlparse(url)
    return parsed.netloc.endswith("pdf.sciencedirectassets.com") and parsed.path.lower().endswith(
        ".pdf"
    )


def _is_sciencedirect_article_url(url: str) -> bool:
    """Return True when *url* points at a ScienceDirect article page."""
    return "/science/article/pii/" in urlparse(url).path.lower()


def _should_use_print_to_pdf_fallback(publisher: PublisherConfig) -> bool:
    """Return whether browser-rendered PDF snapshots are acceptable as fallback.

    ScienceDirect can render preview pages as PDFs via CDP printToPDF. Those are
    not article originals and are rejected later by validation, so skip that
    fallback for Elsevier/ScienceDirect and fail cleanly instead.
    """
    return publisher.name != "sciencedirect"


def _text_looks_like_full_article(text: str) -> bool:
    """Heuristic for full-text article pages that are safe to render as PDF."""
    if not text or len(text) < 10_000:
        return False

    lowered = text.lower()
    markers = (
        "abstract",
        "introduction",
        "materials and methods",
        "experimental",
        "results and discussion",
        "conclusion",
        "references",
    )
    hits = sum(1 for marker in markers if marker in lowered)
    # Reviews / short-form articles often omit "introduction" or "methods"
    # headings while carrying the full body text.  Long pages with at least
    # two structural markers are full articles; require 3+ for shorter ones.
    if len(text) >= 30_000:
        return hits >= 2
    return hits >= 3


def _title_signature_tokens(title: str) -> list[str]:
    """Return distinctive title tokens suitable for page-content matching."""
    seen: set[str] = set()
    tokens: list[str] = []
    for token in re.findall(r"[a-z0-9]+", title.lower()):
        if len(token) < 4 or token in _TITLE_STOPWORDS or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tokens


def _text_mentions_paper(text: str, paper: Paper) -> bool:
    """Return True when page text clearly matches the paper title."""
    if not paper.title:
        return False

    lowered = text.lower()
    tokens = _title_signature_tokens(paper.title)
    if not tokens:
        return False

    hits = sum(1 for token in tokens if token in lowered)
    required_hits = 2 if len(tokens) <= 3 else 3
    return hits >= required_hits


def _text_looks_like_article_page(text: str, paper: Paper | None = None) -> bool:
    """Return True when page text looks like article content, not a challenge."""
    if not text:
        return False

    lowered = text.lower()
    if any(marker.decode("latin1") in lowered for marker in _RENDERED_PDF_CHALLENGE_MARKERS):
        return False

    if _text_looks_like_full_article(text):
        return True

    marker_hits = sum(1 for marker in _LIGHTWEIGHT_ARTICLE_MARKERS if marker in lowered)
    if len(text) >= 1_500 and marker_hits >= 2:
        return True

    return bool(paper and len(text) >= 1_500 and _text_mentions_paper(text, paper))


def _rendered_pdf_looks_like_challenge(data: bytes) -> bool:
    """Return True when a rendered PDF appears to contain a challenge page."""
    lowered = data.lower()
    return any(marker in lowered for marker in _RENDERED_PDF_CHALLENGE_MARKERS)


def _is_tdm_block(html: str) -> bool:
    """Heuristic: return True if *html* looks like a DataDome / TDM block."""
    lower = html.lower()
    return any(kw in lower for kw in _TDM_KEYWORDS)


# ---------------------------------------------------------------------------
# Publisher configuration for Chrome CDP fallback.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PublisherConfig:
    """Configuration for a publisher's Chrome CDP fallback behaviour.

    Each instance describes how to navigate to the article page, locate the
    PDF download button, and capture the resulting PDF for a specific
    publisher or publisher group.
    """

    # Human-readable name (for logging).
    name: str

    # DOI prefixes that identify this publisher (e.g. ``("10.1016/",)``).
    doi_prefixes: tuple[str, ...]

    # Substring expected in the browser page title after navigation.
    # Used to verify the correct page loaded. ``None`` = skip check.
    title_contains: str | None = None

    # CSS selector for the PDF download button/link on the article page.
    # ``None`` = no known selector; the method will wait for any PDF
    # response without clicking.
    pdf_button_selector: str | None = None

    # If *True*, clicking the button opens a new browser tab/popup
    # (ScienceDirect pattern). The method will wait for the popup and
    # capture the PDF response from it.
    pdf_opens_popup: bool = False

    # Domain substrings to block at the network level (``route.abort``).
    block_domains: tuple[str, ...] = ()

    # Maximum seconds to wait for the PDF response after interaction.
    pdf_wait_timeout: int = 25


_PUBLISHERS: tuple[PublisherConfig, ...] = (
    PublisherConfig(
        name="sciencedirect",
        doi_prefixes=("10.1016/",),
        title_contains="ScienceDirect",
    ),
    PublisherConfig(
        name="nature",
        doi_prefixes=("10.1038/",),
        title_contains="Nature",
        pdf_button_selector=".c-pdf-download__link",
    ),
    PublisherConfig(
        name="wiley",
        doi_prefixes=(
            "10.1002/",
            "10.1111/",
            "10.1029/",
        ),
    ),
    PublisherConfig(
        name="seg",
        doi_prefixes=("10.1190/",),
    ),
    PublisherConfig(
        name="oup",
        doi_prefixes=("10.1093/",),
    ),
    PublisherConfig(
        name="springer",
        doi_prefixes=(
            "10.1007/",
            "10.1617/",
        ),
        title_contains="Springer",
    ),
    PublisherConfig(
        name="ieee",
        doi_prefixes=("10.1109/",),
        title_contains="IEEE Xplore",
    ),
    PublisherConfig(
        name="acs",
        doi_prefixes=("10.1021/",),
        title_contains="ACS Publications",
    ),
    PublisherConfig(
        name="rsc",
        doi_prefixes=("10.1039/",),
        title_contains="RSC Publishing",
    ),
    PublisherConfig(
        name="taylor_francis",
        doi_prefixes=(
            "10.1080/",
            "10.1201/",
        ),
    ),
    PublisherConfig(
        name="sage",
        doi_prefixes=("10.1177/",),
    ),
    PublisherConfig(
        name="mdpi",
        doi_prefixes=("10.3390/",),
    ),
    PublisherConfig(
        name="frontiers",
        doi_prefixes=("10.3389/",),
    ),
    PublisherConfig(
        name="degruyter",
        doi_prefixes=("10.1515/",),
    ),
    PublisherConfig(
        name="geoscienceworld",
        doi_prefixes=("10.1785/",),
    ),
    PublisherConfig(
        name="ssrn",
        doi_prefixes=("10.2139/",),
    ),
)


def _detect_publisher(doi: str) -> PublisherConfig | None:
    """Return the :class:`PublisherConfig` matching *doi*, or *None*."""
    if not doi:
        return None
    doi_lower = doi.lower()
    for pub in _PUBLISHERS:
        for prefix in pub.doi_prefixes:
            if doi_lower.startswith(prefix):
                return pub
    return None


def _chrome_entry_url(paper: Paper, publisher: PublisherConfig) -> str:
    """Return the best initial URL for Chrome CDP navigation.

    DOI redirects are the most universal default, but some publishers are
    noticeably less reliable when Chrome starts at ``doi.org``. Use a
    publisher-native landing page when it can be derived deterministically.
    """
    doi = paper.doi
    if publisher.name == "ieee" and doi:
        document_id = doi.rsplit(".", 1)[-1]
        if document_id.isdigit():
            return f"https://ieeexplore.ieee.org/document/{document_id}/"
    if publisher.name == "wiley" and doi.startswith("10.1029/"):
        return f"https://agupubs.onlinelibrary.wiley.com/doi/{doi.upper()}"
    if (
        paper.source_url
        and not paper.source_url.startswith("https://doi.org/")
        and _source_url_matches_publisher(paper.source_url, publisher)
    ):
        return paper.source_url
    return f"https://doi.org/{doi}"


_PUBLISHER_SOURCE_DOMAINS: dict[str, tuple[str, ...]] = {
    "sciencedirect": ("sciencedirect.com", "linkinghub.elsevier.com"),
    "nature": ("nature.com",),
    "wiley": ("onlinelibrary.wiley.com",),
    "seg": ("library.seg.org",),
    "oup": ("academic.oup.com", "oxfordacademic.com"),
    "springer": ("link.springer.com", "springer.com"),
    "ieee": ("ieeexplore.ieee.org",),
    "acs": ("pubs.acs.org",),
    "rsc": ("pubs.rsc.org", "books.rsc.org"),
    "taylor_francis": ("tandfonline.com",),
    "sage": ("sagepub.com", "cnpereading.com"),
    "mdpi": ("mdpi.com",),
    "frontiers": ("frontiersin.org",),
    "degruyter": ("degruyter.com",),
    "geoscienceworld": ("geoscienceworld.org",),
    "ssrn": ("ssrn.com",),
}


def _source_url_matches_publisher(source_url: str, publisher: PublisherConfig) -> bool:
    """Return True when ``source_url`` is already on the publisher's own site.

    Also matches EZProxy-rewritten hosts, e.g.
    ``ift-onlinelibrary-wiley-com.ezproxy.lib.szu.edu.cn`` for Wiley, whose
    host contains the dash-flattened publisher domain (``onlinelibrary-wiley-com``)
    followed by ``ezproxy``.
    """
    host = urlparse(source_url).netloc.lower()
    if not host:
        return False
    allowed = _PUBLISHER_SOURCE_DOMAINS.get(publisher.name, ())
    for domain in allowed:
        if host == domain or host.endswith(f".{domain}"):
            return True
        # Dash-flattened domain (EZProxy rewriting), e.g. "onlinelibrary-wiley-com".
        flattened = domain.replace(".", "-")
        if flattened in host and "ezproxy" in host:
            return True
    return False


def _find_free_port() -> int:
    """Return a currently unused TCP port on localhost."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait_for_cdp(port: int, timeout: float = 15.0) -> None:
    """Wait until Chrome DevTools Protocol is available on *port*."""
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2)
            return
        except Exception:
            await asyncio.sleep(0.5)
    raise TimeoutError(f"Chrome CDP not ready on port {port} after {timeout}s")


def _is_tracking_page(html: str) -> bool:
    """Return *True* if *html* is an EZProxy JavaScript tracking page."""
    return "EZproxyCheckBack" in html or "EZproxyTrack" in html


# ---------------------------------------------------------------------------
# Login / block page detection — two-tier keyword list + size heuristic.
#
# - STRONG keywords: almost certainly indicate a genuine access barrier.
# - WEAK keywords: often appear in navigation chrome on real article pages.
#
# _is_login_page() uses page size to decide which tier to apply:
#   < 2 KB     → always block (TDM challenge, CAPTCHA, error)
#   2–50 KB    → check ALL keywords (likely a pure login/block page)
#   >= 50 KB   → check only STRONG (article content loaded, nav is noise)
# ---------------------------------------------------------------------------
_LOGIN_KEYWORDS_STRONG: tuple[str, ...] = (
    "institutional login",
    "shibboleth",
    "wayfinder",
    "统一身份认证",
    "统一认证",
    "access denied",
    "not authorized",
    "purchase this article",
    "subscribe to this journal",
    "sign in to view",
    "sign in to access",
)

_LOGIN_KEYWORDS_WEAK: tuple[str, ...] = (
    "sign in",
    "sign-in",
    "login",
    "log in",
    "subscribe",
)

_LOGIN_PAGE_SIZE_TINY = 2000  # bytes — always a block page
_LOGIN_PAGE_SIZE_MEDIUM = 50_000  # bytes — check all keywords


def _is_login_page(html: str) -> bool:
    """Heuristic: return *True* if *html* looks like a login / block page.

    Uses a three-tier size heuristic to avoid false positives from
    navigation elements ("sign in" in headers) on real article pages:

    * **Tiny** (< 2 KB) ― always blocked (DataDome challenge,
      CAPTCHA, HTTP error body).
    * **Medium** (2–50 KB) ― check both STRONG and WEAK keywords.
    * **Large** (>= 50 KB) ― check only STRONG keywords; WEAK keywords
      like "sign in" in nav headers are not treated as blocks.
    """
    if not html:
        return True
    lower = html.lower()
    size = len(html)

    # Tiny pages: challenge / error pages.
    if size < _LOGIN_PAGE_SIZE_TINY:
        return True

    # Strong indicators at any page size.
    if any(kw in lower for kw in _LOGIN_KEYWORDS_STRONG):
        return True

    # Medium pages: also check weak keywords (likely a pure login page).
    if size < _LOGIN_PAGE_SIZE_MEDIUM:
        return any(kw in lower for kw in _LOGIN_KEYWORDS_WEAK)

    # Large pages: article content present, don't block on nav noise.
    return False


# ---------------------------------------------------------------------------
# Elsevier / publisher redirect page handling
# ---------------------------------------------------------------------------
_META_REFRESH_RE = re.compile(
    r'<meta\s[^>]*HTTP-EQUIV\s*=\s*["\']?REFRESH["\']?\s[^>]*'
    r'content\s*=\s*["\']\d+;\s*url\s*=\s*["\']?(?P<url>[^"\' >]+)',
    re.IGNORECASE,
)


def _is_redirect_page(html: str) -> bool:
    """Return *True* if *html* looks like an auto-redirect page."""
    return (
        "Redirecting" in html
        or "autoRedirectToURL" in html
        or _META_REFRESH_RE.search(html) is not None
    )


def _extract_meta_refresh_url(html: str, base_url: str) -> str | None:
    """Extract the URL from a ``<meta http-equiv=REFRESH`` tag."""
    m = _META_REFRESH_RE.search(html)
    if m:
        return urljoin(base_url, m.group("url"))
    return None


def _extract_pdf_url(html: str, base_url: str) -> str | None:
    """Extract the first PDF URL from HTML.

    Precedence:
    1. ``<meta name="citation_pdf_url" ...>``
    2. ``<a href="...pdf...">``
    """
    m = _META_PDF_RE.search(html)
    if m:
        return urljoin(base_url, m.group("url"))

    for m in _A_PDF_RE.finditer(html):
        url = m.group("url")
        if url.startswith("data:") or url.startswith("javascript:"):
            continue
        return urljoin(base_url, url)

    return None


# ---------------------------------------------------------------------------
# Downloader
# ---------------------------------------------------------------------------


class InstitutionalDownloader(Downloader):
    """Download PDFs via institutional access (EZProxy or on-campus IP)."""

    name = "institutional"

    def __init__(self, cache, config):
        super().__init__(cache, config)
        self._proxy_url = getattr(config, "institutional_proxy", "").strip()
        self._direct = bool(getattr(config, "institutional_direct", False))

        # Load EZProxy session cookies (Netscape-format cookies.txt).
        cookie_file = getattr(config, "institutional_cookie_file", "")
        if cookie_file:
            self._load_cookie_file(Path(cookie_file))

    # -- lifecycle ---------------------------------------------------------

    async def can_handle(self, paper: Paper) -> bool:
        if not paper.doi:
            return False
        return bool(self._proxy_url) or self._direct

    async def download(self, paper: Paper) -> Path | None:
        doi = paper.doi
        if not doi:
            return None

        dest = self._cache.pdf_path(paper.id)
        dest.parent.mkdir(parents=True, exist_ok=True)

        bucket = bucket_for("institutional")
        await bucket.acquire()

        # Extract DOI components for URL pattern formatting.
        # doi_path: "s41586-024-07155-0" from "10.1038/s41586-024-07155-0"
        doi_path = doi.split("/", 1)[-1] if "/" in doi else doi
        # MDPI CDN pattern fill-ins (10.3390/nu14030588 -> abbr=nu, stem=nu-14-03-00588).
        mdpi_parts = _mdpi_parts(doi)

        # Strategy 1 — known publisher direct-PDF patterns.
        for pattern in _PUBLISHER_PDF_PATTERNS:
            try:
                url = pattern.format(
                    doi=doi,
                    doi_path=doi_path,
                    mdpi_abbr=mdpi_parts[0] if mdpi_parts else "",
                    mdpi_stem=mdpi_parts[1] if mdpi_parts else "",
                )
            except KeyError:
                # Skip patterns that require unknown placeholders (e.g. {doi_pii})
                continue
            result = await self._try_url(self._proxify(url), dest)
            if result is not None:
                return result

        # Strategy 2 — DOI redirect (most universal fallback).
        result = await self._try_url(self._proxify(f"https://doi.org/{doi}"), dest)
        if result is not None:
            return result

        # Strategy 3 — Chrome CDP fallback for any known publisher.
        publisher = _detect_publisher(doi)
        if publisher:
            logger.info(
                "Standard strategies failed for %s — trying Chrome CDP (%s)",
                doi,
                publisher.name,
            )
            # 3a. Preferred: persistent-context direct attach to the real
            # Chrome profile (real fingerprint + live login state). This is
            # the only path that reliably passes Cloudflare Turnstile on
            # ScienceDirect's cfts flow. Falls back to the copied-profile
            # CDP path when the profile is locked (Chrome running).
            real_profile = getattr(self._config, "browser_profile", "") or ""
            if real_profile and Path(real_profile).exists() and HAS_PLAYWRIGHT:
                try:
                    result = await asyncio.wait_for(
                        self._try_chrome_persistent(paper, dest, publisher),
                        timeout=180,
                    )
                except TimeoutError:
                    logger.warning(
                        "Chrome persistent (%s) timed out after 180s for %s",
                        publisher.name,
                        doi,
                    )
                    result = None
                if result is not None:
                    return result
            # 3b. Fallback: existing CDP with copied profile.
            try:
                result = await asyncio.wait_for(
                    self._try_chrome_cdp(paper, dest, publisher),
                    timeout=180,
                )
            except TimeoutError:
                logger.warning(
                    "Chrome CDP (%s) timed out after 180s for %s — skipping",
                    publisher.name,
                    doi,
                )
                result = None
            if result is not None:
                return result

        logger.info("All institutional access strategies exhausted for %s", doi)
        return None

    # -- internal helpers --------------------------------------------------

    def _load_cookie_file(self, path: Path) -> None:
        """Load a Netscape-format cookies.txt into the HTTP client.

        EZProxy exports session cookies with ``expires=0``, but Python's
        :class:`MozillaCookieJar._really_load` silently discards them because
        ``0 <= time.time()``.  We work around this by rewriting ``\\t0\\t`` to
        a far-future timestamp before parsing.
        """
        if not path.exists():
            logger.warning("Cookie file not found: %s", path)
            return
        try:
            # Rewrite session-cookie expiry=0 to a far-future timestamp so
            # MozillaCookieJar._really_load stops throwing them away.
            far_future = 1893456000  # 2030-01-01
            raw = path.read_text(encoding="utf-8")
            raw_fixed = re.sub(r"(?<=\t)0(?=\t)", str(far_future), raw)

            jar = cookiejar.MozillaCookieJar()
            # Use load() with a file-like object so the expiry rewrite takes
            # effect (MozillaCookieJar rejects expiry=0 before the cookie is
            # created).  ignore_discard / ignore_expires are both True so we
            # keep all cookies regardless of their flags.
            import io

            jar._really_load(io.StringIO(raw_fixed), str(path), True, True)

            count = 0
            for c in jar:
                # Also set on the httpx client so they're sent on every request
                self._client.cookies.set(c.name, c.value, domain=c.domain, path=c.path)
                count += 1
            logger.info("Loaded %d cookies from %s", count, path)
        except Exception as exc:
            logger.warning("Failed to load cookies from %s: %s", path, exc)

    async def _browser_entry_url(self, paper: Paper, publisher: PublisherConfig) -> str:
        """Return a browser entry URL, resolving DOI redirects when useful."""
        entry_url = _chrome_entry_url(paper, publisher)
        if not entry_url.startswith("https://doi.org/"):
            return entry_url
        cached = self._cache.get_doi_resolution(paper.doi)
        if cached:
            return cached
        try:
            resp = await self._client.get(
                entry_url,
                headers={"User-Agent": _CHROME_UA},
                follow_redirects=True,
            )
        except Exception as exc:
            logger.debug("Chrome CDP [%s]: DOI resolution failed: %s", publisher.name, exc)
            return entry_url
        resolved = str(resp.url)
        if resolved:
            self._cache.put_doi_resolution(paper.doi, resolved)
        return resolved or entry_url

    def _proxify(self, url: str) -> str:
        """Prepend the EZProxy prefix if configured and NOT in direct mode."""
        if self._proxy_url and not self._direct:
            return f"{self._proxy_url}{url}"
        return url

    def _browser_proxy_url(self, url: str) -> str:
        """Return a browser-friendly proxied URL when EZProxy host rewriting is available."""
        if not self._proxy_url or self._direct:
            return url
        return self._force_browser_proxy_url(url)

    def _force_browser_proxy_url(self, url: str) -> str:
        """Return a browser-friendly proxied URL regardless of direct-mode preference."""
        if not self._proxy_url:
            return url

        proxy_parts = urlparse(self._proxy_url)
        target_parts = urlparse(url)
        if (
            proxy_parts.netloc == "ezproxy.lib.szu.edu.cn"
            and proxy_parts.path.rstrip("/") == "/login"
            and target_parts.scheme == "https"
            and target_parts.netloc
        ):
            proxied_host = f"{target_parts.netloc.replace('.', '-')}.{proxy_parts.netloc}"
            path = target_parts.path or "/"
            query = f"?{target_parts.query}" if target_parts.query else ""
            fragment = f"#{target_parts.fragment}" if target_parts.fragment else ""
            return f"https://{proxied_host}{path}{query}{fragment}"

        return self._proxify(url)

    def _browser_target_candidates(self, entry_url: str, publisher: PublisherConfig) -> list[str]:
        """Return browser navigation targets in priority order."""
        candidates: list[str] = []

        def _add(candidate: str) -> None:
            if candidate and candidate not in candidates:
                candidates.append(candidate)

        direct_target = entry_url
        proxied_target = self._force_browser_proxy_url(entry_url)

        if publisher.name in {"sciencedirect", "wiley", "rsc"} and self._proxy_url:
            _add(proxied_target)
            _add(direct_target)
            return candidates

        _add(self._browser_proxy_url(entry_url))
        if self._proxy_url and self._direct:
            _add(proxied_target)
        _add(direct_target)
        return candidates

    async def _page_looks_like_browser_challenge(self, page) -> bool:
        """Return True while the browser is still on a challenge / verification page."""
        title = (await page.title()).strip().lower()
        if any(
            keyword in title
            for keyword in (
                "please wait",
                "just a moment",
                "security check",
                "security verification",
                "verify",
                "loading",
                "请稍候",
                "请等候",
            )
        ):
            return True

        with contextlib.suppress(Exception):
            html_snippet = (await page.content())[:2000].lower()
            if any(
                marker in html_snippet
                for marker in (
                    "cdn-cgi/challenge-platform",
                    "turnstile",
                    "security verification",
                    "just a moment",
                    "please wait",
                )
            ):
                return True

        return False

    async def _page_matches_publisher(self, page, publisher: PublisherConfig, paper: Paper) -> bool:
        """Return True when the browser appears to be on the publisher's article page."""
        if await self._page_looks_like_browser_challenge(page):
            return False

        title = await page.title()
        current_url = page.url
        url_matches = _source_url_matches_publisher(current_url, publisher)

        if publisher.title_contains and publisher.title_contains in title and url_matches:
            return True

        if publisher.name == "sciencedirect":
            current_url_lower = current_url.lower()
            if "/science/article/pii/" in current_url_lower:
                with contextlib.suppress(Exception):
                    has_meta = await page.evaluate(
                        "() => !!document.querySelector("
                        '\'meta[name="citation_pii"], '
                        'meta[name="citation_doi"], meta[name="citation_title"]\''
                        ")"
                    )
                    if has_meta:
                        return True

        has_article_meta = False
        with contextlib.suppress(Exception):
            has_article_meta = await page.evaluate(
                "() => !!document.querySelector("
                '\'meta[name="citation_doi"], meta[name="citation_title"], '
                'meta[name="citation_pdf_url"], meta[name="dc.Title"]\''
                ")"
            )
        if has_article_meta and url_matches:
            return True

        with contextlib.suppress(Exception):
            body_text = await page.locator("body").inner_text()
            if url_matches and _text_looks_like_article_page(f"{title}\n{body_text}", paper):
                return True

        return False

    async def _try_url(self, url: str, dest: Path) -> Path | None:
        """Fetch *url* and save to *dest* if it is (or resolves to) a PDF.

        Handles:
        * Direct PDF response.
        * EZProxy JavaScript tracking page (follows the JS redirect).
        * HTML page with ``citation_pdf_url`` or ``.pdf`` link.
        * Login / block pages (skipped).
        """
        logger.debug("Institutional: trying %s", url)

        resp = await self._fetch(url)
        if resp is None:
            return None

        # Handle EZProxy tracking page (JavaScript location.href redirect).
        resp = await self._handle_tracking_page(resp)
        if resp is None:
            return None

        # Safety check: the followed response might still be a tracking
        # page if EZProxy requires full JS execution (form auto-submit).
        if _is_tracking_page(resp.text):
            logger.debug("Institutional: tracking page requires JS, giving up on %s", url)
            return None

        # Direct PDF hit.
        ct = resp.headers.get("content-type", "")
        if "application/pdf" in ct:
            dest.write_bytes(resp.content)
            logger.info("Saved institutional PDF from %s", url)
            return dest

        # HTML → extract PDF link.
        if "text/html" in ct:
            html = resp.text

            # Handle publisher redirect pages (e.g. Elsevier LinkingHub
            # / retrieve pages with meta-refresh + auto-redirect).
            if _is_redirect_page(html):
                redirect_url = _extract_meta_refresh_url(html, str(resp.url))
                if redirect_url:
                    logger.debug("Institutional: following redirect to %s", redirect_url)
                    redirect_resp = await self._fetch(redirect_url)
                    if redirect_resp:
                        # Check if redirect target is a PDF
                        rct = redirect_resp.headers.get("content-type", "")
                        if "application/pdf" in rct:
                            dest.write_bytes(redirect_resp.content)
                            logger.info("Saved institutional PDF from %s", redirect_url)
                            return dest
                        # If still HTML, try to extract PDF from it
                        if "text/html" in rct and not _is_login_page(redirect_resp.text):
                            pdf_url = _extract_pdf_url(redirect_resp.text, str(redirect_resp.url))
                            if pdf_url:
                                pdf_resp = await self._fetch(pdf_url)
                                if pdf_resp and "application/pdf" in pdf_resp.headers.get(
                                    "content-type", ""
                                ):
                                    dest.write_bytes(pdf_resp.content)
                                    return dest
                # If we couldn't follow refresh, continue to normal PDF extraction
                # on the current page.

            # Try PDF URL extraction BEFORE login check — for large pages
            # (Nature 608 KB, Wiley 414 KB) that have article content + nav
            # chrome, extracting a meta tag is cheap and may avoid Chrome CDP.
            pdf_url = _extract_pdf_url(html, str(resp.url))
            if pdf_url:
                logger.debug("Institutional: extracted PDF URL %s from %s", pdf_url, url)
                pdf_resp = await self._fetch(pdf_url)
                if pdf_resp and "application/pdf" in pdf_resp.headers.get("content-type", ""):
                    dest.write_bytes(pdf_resp.content)
                    logger.info("Saved institutional PDF (from HTML) from %s", pdf_url)
                    return dest

            # Now check for login / block pages (after PDF extraction, so
            # pages with article content + nav "sign in" still get parsed).
            if _is_login_page(html):
                logger.debug("Institutional: login/block page at %s, skipping", url)
                return None

        return None

    async def _handle_tracking_page(self, resp: httpx.Response) -> httpx.Response | None:
        """If *resp* is an EZProxy JS tracking page, follow the redirect.

        EZProxy sometimes returns a 200 HTML page with a JavaScript
        ``location.href`` redirect (``EZproxyCheckBack``) instead of an
        HTTP 302.  This method detects that page, extracts the target URL,
        and follows it.

        Two common EZProxy tracking patterns are handled:

        1. ``location.href = "..."`` — extracted and followed directly.
        2. ``EZproxyCheckBack()`` form — re-fetch the same URL; the
           proxy serves the real content on the second request after the
           session is confirmed.
        """
        ct = resp.headers.get("content-type", "")
        if "text/html" not in ct:
            return resp
        if not _is_tracking_page(resp.text):
            return resp

        # Pattern 1: direct JavaScript redirect.
        m = _EZPROXY_TRACKING_RE.search(resp.text)
        if m:
            redirect_url = m.group("url")
            logger.debug("Following EZProxy tracking redirect to %s", redirect_url)
            return await self._fetch(redirect_url)

        # Pattern 2: EZproxyCheckBack form — no JS redirect found.
        # Extract the original target URL from the proxy's ``url``
        # parameter.  The session cookie was already set by the tracking
        # page response, so re-fetching the proxified URL should now
        # return the real content.
        parsed = urlparse(str(resp.url))
        params = parse_qs(parsed.query)
        original_urls = params.get("url")
        if original_urls:
            logger.debug("Re-fetching proxied URL after tracking page: %s", original_urls[0])
            return await self._fetch(self._proxify(original_urls[0]))
        logger.warning("EZProxy tracking page with no url param — cannot follow")
        return None

    async def _fetch(self, url: str) -> httpx.Response | None:
        """Perform a single GET with standard timeout and redirect following.

        Returns the response on success, or *None* on any HTTP / network
        error.
        """
        try:
            resp = await self._client.get(
                url, follow_redirects=True, headers={"User-Agent": _CHROME_UA}
            )
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as exc:
            logger.debug("Institutional: HTTP %s for %s", exc.response.status_code, url)
            return None
        except httpx.RequestError as exc:
            logger.debug("Institutional: request error for %s: %s", url, exc)
            return None

    # -- Chrome CDP fallback -------------------------------------------------

    @staticmethod
    def _chrome_cookies_for_playwright(path: str) -> list[dict]:
        """Re-read the Netscape cookie file into Playwright-compatible format.

        Returns a list of cookie dicts suitable for ``context.add_cookies()``.
        Returns an empty list when the file can't be read.
        """
        try:
            raw = Path(path).read_text(encoding="utf-8")
            cookies: list[dict] = []
            for line in raw.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 7:
                    cookies.append(
                        {
                            "name": parts[5],
                            "value": parts[6],
                            "domain": parts[0],
                            "path": parts[2],
                            "secure": parts[3] == "TRUE",
                            "httpOnly": False,
                            "sameSite": "Lax",
                        }
                    )
            return cookies
        except Exception as exc:
            logger.debug("Failed to read cookies for Chrome CDP: %s", exc)
            return []

    async def _try_chrome_persistent(
        self,
        paper: Paper,
        dest: Path,
        publisher: PublisherConfig,
    ) -> Path | None:
        """Download a PDF using the REAL Chrome profile via Playwright's
        ``launch_persistent_context`` (no copying, no CDP port).

        This is the approach proven in the revenue-trial project for passing
        Cloudflare Turnstile: attach to the real user-data dir + profile
        directory so the browser keeps its real fingerprint, live cookies
        (incl. cf_clearance) and institutional session.  Works only when the
        target Chrome profile is not currently running (profile lock).
        """
        if not HAS_PLAYWRIGHT:
            return None
        real_profile = getattr(self._config, "browser_profile", "") or ""
        if not real_profile or not Path(real_profile).exists():
            return None

        # Chrome locks the profile dir; require it to be free.
        _probe = Path(real_profile) / "Default" / "Network" / "Cookies"
        _locked = False
        if _probe.exists():
            try:
                with open(_probe, "rb"):
                    pass
            except OSError:
                _locked = True
        if _locked:
            logger.debug(
                "Chrome persistent: profile %s is locked (Chrome running) — "
                "falling back to copied-profile CDP",
                real_profile,
            )
            return None

        chrome_path = resolve_browser_executable()
        if not chrome_path:
            return None

        # Resolve which profile directory to attach (Default unless the
        # config points at a specific one).
        _src_root = Path(real_profile)
        profile_dir = "Default"
        if (_src_root / "Profile 1").exists() and not (_src_root / "Default").exists():
            profile_dir = "Profile 1"

        try:
            async with async_playwright() as pw:
                launch_kwargs: dict[str, object] = {
                    "user_data_dir": str(_src_root),
                    "headless": False,
                    "args": [
                        f"--profile-directory={profile_dir}",
                        "--no-first-run",
                        "--no-default-browser-check",
                        "--disable-notifications",
                        "--disable-permissions-api",
                        "--deny-permission-prompts",
                    ],
                }
                if chrome_path:
                    launch_kwargs["executable_path"] = chrome_path
                else:
                    launch_kwargs["channel"] = "chrome"

                context = await pw.chromium.launch_persistent_context(**launch_kwargs)
                try:
                    # Auto-accept dialogs (permission / EZProxy confirmations).
                    context.on(
                        "dialog",
                        lambda dialog: asyncio.create_task(dialog.accept()),
                    )
                    page = context.pages[0] if context.pages else await context.new_page()
                    pdf_data: bytes | None = None

                    async def _capture_pdf(response):
                        nonlocal pdf_data
                        ct = response.headers.get("content-type", "")
                        if "application/pdf" in ct:
                            try:
                                body = await response.body()
                                if len(body) > 10000:
                                    pdf_data = body
                            except Exception:
                                pass

                    context.on("response", _capture_pdf)

                    entry_url = await self._browser_entry_url(paper, publisher)
                    candidates = self._browser_target_candidates(entry_url, publisher)
                    loaded = False
                    for target in candidates:
                        try:
                            await page.goto(
                                target,
                                wait_until="domcontentloaded",
                                timeout=60000,
                            )
                        except Exception:
                            await asyncio.sleep(3)
                            continue
                        await asyncio.sleep(3)
                        for _ in range(45):  # up to ~90s challenge wait
                            if await self._page_matches_publisher(page, publisher, paper):
                                loaded = True
                                break
                            challenge = await self._page_looks_like_browser_challenge(page)
                            if challenge:
                                # Revenue-trial approach: click a visible
                                # Turnstile checkbox if present, then wait for
                                # the token (invisible challenges resolve by
                                # themselves in a real-profile browser).
                                with contextlib.suppress(Exception):
                                    box = page.locator(
                                        ".cf-turnstile, #cf-turnstile, iframe[src*='turnstile']"
                                    )
                                    if await box.count() >= 1:
                                        await box.first.click(timeout=3000)
                                with contextlib.suppress(Exception):
                                    await page.wait_for_function(
                                        """() => {
                                            const h = document.querySelector(
                                                'input[name="cf-turnstile-response"]');
                                            if (h && h.value) return true;
                                            if (typeof window.turnstile !== 'undefined') {
                                                try {
                                                    const api = window.turnstile;
                                                    if (typeof api.getResponse === 'function'
                                                        && api.getResponse()) return true;
                                                } catch (e) {}
                                            }
                                            return false;
                                        }""",
                                        timeout=15000,
                                    )
                                continue
                            await asyncio.sleep(2)
                        if loaded:
                            break

                    if not loaded:
                        logger.debug(
                            "Chrome persistent [%s]: article page not loaded",
                            publisher.name,
                        )
                        return None

                    # --- ScienceDirect: click View PDF (button enabled in the
                    # real profile) and wait for the PDF response ---
                    if publisher.name == "sciencedirect":
                        pii = await page.evaluate(
                            "() => {"
                            " const m = window.location.href.match('/pii/([A-Z0-9]+)');"
                            " return m ? m[1] : null;"
                            " }"
                        )
                        if pii:
                            # Wait for the View PDF button to enable.
                            for _ in range(60):
                                state = await page.evaluate(
                                    """() => {
                                        for (const el of document.querySelectorAll('a')) {
                                            const aria = el.getAttribute('aria-label') || '';
                                            if (/view\\s*pdf/i.test(aria)) {
                                                return el.getAttribute('aria-disabled')
                                                    === 'true' ? 'disabled' : 'enabled';
                                            }
                                        }
                                        return 'no-button';
                                    }"""
                                )
                                if state == "enabled":
                                    break
                                await asyncio.sleep(1)
                            if state == "enabled":
                                clicked = await page.evaluate(
                                    """() => {
                                        for (const el of document.querySelectorAll('a')) {
                                            const aria = el.getAttribute('aria-label') || '';
                                            if (/view\\s*pdf/i.test(aria)) {
                                                el.click();
                                                return true;
                                            }
                                        }
                                        return false;
                                    }"""
                                )
                                if clicked:
                                    # Wait for the PDF response; the new tab
                                    # auto-passes Turnstile in the real profile.
                                    for _ in range(120):
                                        if pdf_data:
                                            break
                                        await asyncio.sleep(1)
                                    if pdf_data and pdf_data[:4] == b"%PDF":
                                        dest.write_bytes(pdf_data)
                                        logger.info(
                                            "Downloaded SD PDF via persistent profile "
                                            "for %s (%d bytes)",
                                            paper.doi,
                                            len(pdf_data),
                                        )
                                        return dest

                    # Generic fallback: capture PDF responses or printToPDF.
                    if not pdf_data:
                        body_text = ""
                        with contextlib.suppress(Exception):
                            body_text = (
                                f"{await page.title()}\n{await page.locator('body').inner_text()}"
                            )
                        if _text_looks_like_article_page(body_text, paper):
                            with contextlib.suppress(Exception):
                                cdp = await context.new_cdp_session(page)
                                result = await cdp.send(
                                    "Page.printToPDF",
                                    {
                                        "printBackground": True,
                                        "preferCSSPageSize": True,
                                        "marginTop": 0.4,
                                        "marginBottom": 0.4,
                                        "marginLeft": 0.4,
                                        "marginRight": 0.4,
                                    },
                                )
                                import base64

                                raw = base64.b64decode(result["data"])
                                if len(raw) > 5000 and raw[:4] == b"%PDF":
                                    dest.write_bytes(raw)
                                    logger.info(
                                        "Downloaded PDF via persistent printToPDF "
                                        "for %s (%d bytes)",
                                        paper.doi,
                                        len(raw),
                                    )
                                    return dest
                    return None
                finally:
                    with contextlib.suppress(Exception):
                        await context.close()
        except Exception as exc:
            logger.debug("Chrome persistent: error: %s", exc)
            return None

    async def _try_chrome_cdp(
        self,
        paper: Paper,
        dest: Path,
        publisher: PublisherConfig,
    ) -> Path | None:
        """Download a PDF using real Chrome via CDP, configured for *publisher*.

        Works for any publisher where automated HTTP clients fail (DataDome,
        JS challenges, complex auth flows).  Launches real Chrome with a
        temporary profile, connects via Playwright CDP, navigates through
        EZProxy, interacts with the publisher's PDF button, and captures the
        resulting PDF.

        Three interaction patterns, controlled by *publisher* config:

        * **Popup** (``pdf_opens_popup=True``) — clicking the button opens a
          new tab (ScienceDirect).  The method waits for the popup and
          captures the PDF response.
        * **Known selector** (``pdf_button_selector`` set, no popup) — clicks
          the button and captures the download (Nature, Wiley).
        * **Generic** (no selector) — waits for any PDF response to arrive
          from the page's network traffic, then falls back to
          ``Page.printToPDF``.

        Returns the local path on success, or *None* on any failure.
        """
        if not HAS_PLAYWRIGHT:
            logger.debug("Chrome CDP: Playwright not installed — skipping")
            return None

        chrome_path = resolve_browser_executable()
        if not chrome_path:
            logger.debug("Chrome CDP: Chrome executable not found")
            return None

        # Load cookies for Playwright from the configured cookie file.
        cookie_file = getattr(self._config, "institutional_cookie_file", "")
        pw_cookies = self._chrome_cookies_for_playwright(cookie_file) if cookie_file else []
        logger.debug("Chrome CDP: loaded %d cookies for Playwright", len(pw_cookies))

        tmp_dir: str | None = None
        chrome_proc: subprocess.Popen | None = None
        pdf_data: bytes | None = None

        try:
            # 1. Use a persistent user-data directory so Cloudflare
            #    clearance cookies survive across Chrome launches.
            #    If LITKIT_BROWSER_PROFILE points at a real Chrome profile
            #    (real fingerprint + login state), copy it so challenges
            #    (SSRN/Sage Cloudflare) pass; Chrome locks the source dir.
            real_profile = getattr(self._config, "browser_profile", "") or ""
            tmp_dir = str(default_profile_dir("institutional"))
            if real_profile and Path(real_profile).exists():
                tmp_dir = str(default_profile_dir("institutional_real"))
                import shutil as _shutil

                _src_root = Path(real_profile)
                _src_def = _src_root / "Default" if (_src_root / "Default").exists() else _src_root
                _work = Path(tmp_dir)
                if _work.exists():
                    _shutil.rmtree(_work, ignore_errors=True)
                _work.mkdir(parents=True, exist_ok=True)
                # Chrome expects --user-data-dir to contain "Default/" plus a
                # root-level "Local State" (holds the cookie encryption key).
                # Copy those so the real fingerprint + login cookies survive.
                _ls = _src_root / "Local State"
                if _ls.exists():
                    with contextlib.suppress(OSError):
                        _shutil.copy2(_ls, _work / "Local State")
                (_work / "Default").mkdir(parents=True, exist_ok=True)
                for _name in (
                    "Cookies",
                    "Network",
                    "Preferences",
                    "Web Data",
                    "Login Data",
                    "Local Storage",
                    "Session Storage",
                    "Secure Preferences",
                ):
                    _f = _src_def / _name
                    if _f.exists():
                        _dst = _work / "Default" / _name
                        try:
                            if _f.is_dir():
                                _shutil.copytree(_f, _dst, dirs_exist_ok=True)
                            else:
                                _shutil.copy2(_f, _dst)
                        except OSError:
                            pass
                # Chrome >= 117 stores the cookie DB under Network/Cookies.
                _net_src = _src_def / "Network"
                if _net_src.exists():
                    _net_dst = _work / "Default" / "Network"
                    _net_dst.mkdir(parents=True, exist_ok=True)
                    for _cname in ("Cookies", "Cookies-journal"):
                        _cf = _net_src / _cname
                        if _cf.exists():
                            with contextlib.suppress(OSError):
                                _shutil.copy2(_cf, _net_dst / _cname)
                logger.debug("Chrome CDP: using real profile %s (copied to %s)", _src_def, _work)
            Path(tmp_dir).mkdir(parents=True, exist_ok=True)
            Path(tmp_dir).mkdir(parents=True, exist_ok=True)

            # 2. Pick a free TCP port (avoid TIME_WAIT conflicts from
            #    sequential Chrome CDP calls).
            cdp_port = _find_free_port()

            # 3. Launch real Chrome with remote debugging.
            chrome_proc = subprocess.Popen(
                [
                    chrome_path,
                    f"--user-data-dir={tmp_dir}",
                    f"--remote-debugging-port={cdp_port}",
                    "--remote-allow-origins=*",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-gpu",
                    "--disable-software-rasterizer",
                    # Suppress permission prompts that block automated
                    # navigation (notifications / media / geolocation) —
                    # these popups previously stalled CDP runs that used a
                    # copied real Chrome profile.
                    "--disable-notifications",
                    "--disable-geolocation",
                    "--disable-permissions-api",
                    "--disable-popup-blocking",
                    "--deny-permission-prompts",
                    *browser_launch_args(),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **spawn_process_kwargs(),
            )

            # 4. Wait for CDP to become available.
            try:
                await _wait_for_cdp(cdp_port, 15)
            except TimeoutError:
                logger.debug("Chrome CDP: browser did not start in time")
                return None

            # 5. Connect via Playwright.
            cdp_url = f"http://127.0.0.1:{cdp_port}"
            async with async_playwright() as pw:
                browser = await pw.chromium.connect_over_cdp(cdp_url)
                context = browser.contexts[0] if browser.contexts else await browser.new_context()

                # Inject EZProxy cookies — but never overwrite the live
                # profile session (see note below).
                if pw_cookies:
                    existing_ez = {f"{c['domain']}|{c['name']}" for c in await context.cookies()}
                    fresh_ez = [
                        c
                        for c in pw_cookies
                        if f"{c.get('domain', '')}|{c.get('name', '')}" not in existing_ez
                    ]
                    if fresh_ez:
                        await context.add_cookies(fresh_ez)
                        logger.debug(
                            "Chrome CDP: injected %d fresh EZProxy cookies (skipped %d existing)",
                            len(fresh_ez),
                            len(pw_cookies) - len(fresh_ez),
                        )

                # Auto-accept any JS dialogs (alert/confirm/prompt) so a
                # leftover permission or EZProxy confirmation dialog never
                # stalls the automation.
                context.on(
                    "dialog",
                    lambda dialog: asyncio.create_task(dialog.accept()),
                )

                # Inject publisher-specific cookies (e.g. ScienceDirect
                # SD_REMOTEACCESS for on-campus IP auth, ACS session cookies).
                # IMPORTANT: never overwrite cookies that already exist in the
                # persistent profile — the live profile session (fresh EZProxy
                # login + current cf_clearance) must win over stale files,
                # otherwise SD/CF auth breaks and the View PDF button stays
                # disabled forever.
                _project_root = Path(__file__).resolve().parent.parent.parent.parent
                existing = {f"{c['domain']}|{c['name']}" for c in await context.cookies()}
                for _cookie_file in (
                    "www.sciencedirect.com_cookies.txt",
                    "pubs.acs.org_cookies.txt",
                ):
                    _cp = _project_root / _cookie_file
                    if not _cp.exists():
                        continue
                    _ck = self._chrome_cookies_for_playwright(str(_cp))
                    _fresh = [
                        c
                        for c in _ck
                        if f"{c.get('domain', '')}|{c.get('name', '')}" not in existing
                    ]
                    if _fresh:
                        await context.add_cookies(_fresh)
                        logger.debug(
                            "Chrome CDP: loaded %d fresh cookies from %s (skipped %d existing)",
                            len(_fresh),
                            _cookie_file,
                            len(_ck) - len(_fresh),
                        )

                page = await context.new_page()

                # Block publisher-specific domains at the network level
                # (e.g. DataDome for ScienceDirect).
                if publisher.block_domains:

                    async def _block_publisher_routes(route):
                        for domain in publisher.block_domains:
                            if domain in route.request.url:
                                await route.abort()
                                return
                        await route.continue_()

                    await page.route("**/*", _block_publisher_routes)

                # Capture PDF responses from any page / popup.
                async def _capture_pdf(response):
                    nonlocal pdf_data
                    ct = response.headers.get("content-type", "")
                    if "application/pdf" in ct:
                        try:
                            body = await response.body()
                            if len(body) > 10000:
                                pdf_data = body
                        except Exception:
                            pass

                context.on("response", _capture_pdf)

                # 5. Navigate to article through a publisher-appropriate target.
                entry_url = await self._browser_entry_url(paper, publisher)
                loaded = False
                for browser_target in self._browser_target_candidates(entry_url, publisher):
                    logger.debug(
                        "Chrome CDP [%s]: navigating to %s",
                        publisher.name,
                        browser_target,
                    )
                    try:
                        await page.goto(
                            browser_target,
                            wait_until="domcontentloaded",
                            timeout=60000,
                        )
                    except Exception as exc:
                        logger.debug("Chrome CDP [%s]: navigation error: %s", publisher.name, exc)
                        # EZProxy JS redirects may still be in flight (the page
                        # briefly lands on chrome-error:// before jumping to the
                        # rewritten publisher host). Give it a moment, then
                        # decide whether the target is really dead.
                        await asyncio.sleep(3)
                        try:
                            if page.url.startswith("chrome-error://") or not page.url:
                                logger.debug(
                                    "Chrome CDP [%s]: target stuck on error page, skipping",
                                    publisher.name,
                                )
                                continue
                        except Exception:
                            continue

                    # Wait for JS challenges and publisher redirects to settle.
                    await asyncio.sleep(3)

                    for cf_wait in range(60):  # up to ~120 seconds
                        title = await page.title()
                        if await self._page_matches_publisher(page, publisher, paper):
                            if cf_wait > 0:
                                logger.info(
                                    "Chrome CDP [%s]: article page ready after %.0fs (title=%r)",
                                    publisher.name,
                                    (cf_wait + 1) * 2,
                                    title,
                                )
                            loaded = True
                            break

                        challenge = await self._page_looks_like_browser_challenge(page)
                        if challenge:
                            if cf_wait == 0 or cf_wait % 10 == 0:
                                logger.info(
                                    (
                                        "Chrome CDP [%s]: challenge active "
                                        "(title=%r), waiting... (%.0fs)"
                                    ),
                                    publisher.name,
                                    title,
                                    (cf_wait + 1) * 2,
                                )
                            # Cloudflare/DDoS-Guard challenges are intermittent:
                            # reloading every ~20s gives a fresh challenge instance
                            # that frequently passes on the retry.
                            if cf_wait > 0 and cf_wait % 10 == 0:
                                with contextlib.suppress(Exception):
                                    await page.reload(wait_until="load", timeout=30000)
                                logger.debug(
                                    "Chrome CDP [%s]: reloaded challenge page",
                                    publisher.name,
                                )
                            await asyncio.sleep(2)
                            continue

                        if cf_wait == 0 or cf_wait % 10 == 0:
                            logger.debug(
                                "Chrome CDP [%s]: waiting for publisher page (title=%r, url=%s)",
                                publisher.name,
                                title,
                                page.url[:120],
                            )
                        await asyncio.sleep(2)

                    if loaded:
                        break

                if not loaded:
                    title = await page.title()
                    logger.debug(
                        "Chrome CDP [%s]: unexpected page title %r",
                        publisher.name,
                        title,
                    )
                    await browser.close()
                    return None

                logger.debug("Chrome CDP [%s]: article page loaded", publisher.name)
                article_page_url = page.url
                allow_sciencedirect_rendered_fallback = False
                skip_generic_pdf_interaction = False

                # --- ScienceDirect: pdfft navigation -> S3 -> a.download ---
                if publisher.name == "sciencedirect":
                    try:
                        current_url = page.url
                        logger.debug(
                            "Chrome CDP [sciencedirect]: current URL: %s",
                            current_url[:120],
                        )

                        # Extract PII from URL or page metadata.
                        pii = await page.evaluate(
                            "() => {"
                            " const m = window.location.href.match('/pii/([A-Z0-9]+)');"
                            " return m ? m[1] : null;"
                            " }"
                        )
                        if not pii:
                            pii = await page.evaluate(
                                "() => document.querySelector("
                                "'meta[name=\"citation_pii\"]'"
                                ")?.content || null"
                            )
                        if not pii:
                            logger.debug("Chrome CDP [sciencedirect]: no PII in URL")
                            pii = None

                        if pii:
                            # Keep the currently loaded article URL when the
                            # browser already resolved through EZProxy onto a
                            # readable full-text page. Switching back to the
                            # direct ScienceDirect host can re-trigger access
                            # checks and lose the article context.
                            article_url = page.url.split("?", 1)[0]
                            clean_url = article_url
                            if not _is_sciencedirect_article_url(current_url):
                                clean_url = (
                                    f"https://www.sciencedirect.com/science/article/pii/{pii}"
                                )
                                logger.debug(
                                    "Chrome CDP [sciencedirect]: navigating to clean article URL"
                                )
                                try:
                                    await page.goto(clean_url, wait_until="load", timeout=30000)
                                    await asyncio.sleep(2)
                                    article_url = page.url.split("?", 1)[0]
                                except Exception:
                                    pass

                            with contextlib.suppress(Exception):
                                body_text = await page.locator("body").inner_text()
                                allow_sciencedirect_rendered_fallback = (
                                    _text_looks_like_full_article(body_text)
                                )

                            # Try to find pdfft link on the article page.
                            pdfft_url = await page.evaluate(
                                """(pii) => {
                                    // Try direct pdfft links first
                                    for (const a of document.querySelectorAll('a[href*="pdfft"]')) {
                                        if (a.href.includes(pii)) return a.href;
                                    }
                                    // Try data-doi / data-pii links
                                    for (const a of document.querySelectorAll(
                                        'a[href*="/pdf"], a[href*="download"]'
                                    )) {
                                        if (a.href.includes(pii)) return a.href;
                                    }
                                    return null;
                                }""",
                                pii,
                            )

                            # NEW: wait for the "View PDF" button to become
                            # enabled (SD lazily builds the pdfft?md5=... link;
                            # while disabled it only shows a spinner) and click
                            # it — the click runs the full JS flow (incl. any
                            # Cloudflare challenge) in the real browser, and the
                            # global response listener captures the real PDF.
                            # Prefer the button over a bare constructed pdfft
                            # URL: the button carries the md5-signed link that
                            # the cfts flow actually accepts.
                            clicked = await page.evaluate(
                                """(pii) => {
                                    const btn = (() => {
                                        for (const el of document.querySelectorAll('a')) {
                                            const aria = el.getAttribute('aria-label') || '';
                                            if (/view\\s*pdf/i.test(aria)) return el;
                                        }
                                        return null;
                                    })();
                                    if (!btn) return 'no-button';
                                    if (btn.getAttribute('aria-disabled') === 'true') {
                                        return 'still-disabled';
                                    }
                                    btn.click();
                                    return 'clicked';
                                }""",
                                pii,
                            )
                            if clicked == "still-disabled":
                                # Poll up to 90s for the button to enable.
                                for _ in range(90):
                                    await asyncio.sleep(1)
                                    state = await page.evaluate(
                                        """() => {
                                            for (const el of document.querySelectorAll('a')) {
                                                const aria = el.getAttribute('aria-label') || '';
                                                if (/view\\s*pdf/i.test(aria)) {
                                                    const disabled =
                                                        el.getAttribute('aria-disabled') === 'true';
                                                    return disabled ? 'still-disabled' : 'enabled';
                                                }
                                            }
                                            return 'no-button';
                                        }"""
                                    )
                                    if state == "enabled":
                                        await page.evaluate(
                                            """() => {
                                                for (const el of document.querySelectorAll('a')) {
                                                    const aria =
                                                        el.getAttribute('aria-label') || '';
                                                    if (/view\\s*pdf/i.test(aria)) {
                                                        el.click();
                                                        return true;
                                                    }
                                                }
                                                return false;
                                            }"""
                                        )
                                        clicked = "clicked"
                                        break
                                    if pdf_data:
                                        break
                            # After click: wait for PDF response (captured by
                            # the global listener) — the new tab runs the
                            # challenge flow automatically.
                            for _ in range(60):
                                if pdf_data:
                                    break
                                await asyncio.sleep(1)
                            if pdf_data and pdf_data[:4] == b"%PDF":
                                dest.write_bytes(pdf_data)
                                logger.info(
                                    "Downloaded SD PDF via View-PDF click for %s (%d bytes)",
                                    paper.doi,
                                    len(pdf_data),
                                )
                                await browser.close()
                                return dest
                            logger.debug(
                                "Chrome CDP [sciencedirect]: View PDF click "
                                "did not yield PDF (state=%s)",
                                clicked,
                            )

                            # If no pdfft link found, try constructing it directly
                            # (Chrome with valid auth should handle the redirect).
                            if not pdfft_url:
                                logger.debug(
                                    "Chrome CDP [sciencedirect]: no pdfft link found, "
                                    "trying direct construction"
                                )
                                pdfft_url = f"{article_url.rstrip('/')}/pdfft"

                            logger.debug("Chrome CDP [sciencedirect]: pdfft: %s", pdfft_url[:80])

                            # Navigate to the pdfft endpoint, then WAIT for the
                            # Cloudflare/Turnstile challenge to pass *in the real
                            # browser* (real fingerprint auto-passes within a few
                            # seconds). The global response listener captures the
                            # real PDF bytes as soon as the S3 stream arrives —
                            # do NOT give up after a fixed 5s like before.
                            with contextlib.suppress(Exception):
                                await page.goto(
                                    pdfft_url,
                                    wait_until="domcontentloaded",
                                    timeout=60000,
                                )
                            await asyncio.sleep(3)

                            s3_url = page.url
                            ct = await page.evaluate("document.contentType")

                            # Poll up to ~90s: challenge may take a while, and
                            # once it passes the PDF response fires on the wire.
                            for _ in range(90):
                                if pdf_data:
                                    break
                                ct = await page.evaluate("document.contentType")
                                if ct == "application/pdf":
                                    break
                                await asyncio.sleep(1)

                            if pdf_data and pdf_data[:4] == b"%PDF":
                                dest.write_bytes(pdf_data)
                                logger.info(
                                    "Downloaded SD PDF via Chrome CDP after challenge "
                                    "for %s (%d bytes)",
                                    paper.doi,
                                    len(pdf_data),
                                )
                                await browser.close()
                                return dest

                            if ct != "application/pdf" or not _is_sciencedirect_asset_pdf_url(
                                s3_url
                            ):
                                logger.debug(
                                    "Chrome CDP [sciencedirect]: "
                                    "failed to reach S3 PDF: CT=%s, URL=%s",
                                    ct,
                                    s3_url[:80],
                                )
                                with contextlib.suppress(Exception):
                                    await page.goto(article_url, wait_until="load", timeout=30000)
                                    await asyncio.sleep(2)
                                if allow_sciencedirect_rendered_fallback:
                                    skip_generic_pdf_interaction = True
                                    logger.debug(
                                        "Chrome CDP [sciencedirect]: "
                                        "keeping loaded article page for printToPDF fallback"
                                    )
                            else:
                                logger.debug(
                                    "Chrome CDP [sciencedirect]: S3 URL reached, downloading"
                                )

                                dl_tmp = dest.with_name(dest.name + ".tmp")
                                if dl_tmp.exists():
                                    dl_tmp.unlink()

                                try:
                                    async with page.expect_download(timeout=30000) as di:
                                        await page.evaluate(
                                            """(url) => {
                                                const a = document.createElement('a');
                                                a.href = url;
                                                a.download = 'paper.pdf';
                                                document.body.appendChild(a);
                                                a.click();
                                                document.body.removeChild(a);
                                            }""",
                                            s3_url,
                                        )
                                    dl = await di.value
                                    await dl.save_as(str(dl_tmp))
                                    await asyncio.sleep(3)

                                    if dl_tmp.exists() and dl_tmp.stat().st_size > 10000:
                                        data = dl_tmp.read_bytes()
                                        if data[:4] == b"%PDF":
                                            if dest.exists():
                                                dest.unlink()
                                            dl_tmp.rename(dest)
                                            logger.info(
                                                "Downloaded SD PDF via Chrome CDP "
                                                "for %s (%d bytes)",
                                                paper.doi,
                                                len(data),
                                            )
                                            await browser.close()
                                            return dest
                                except Exception as exc:
                                    logger.debug(
                                        "Chrome CDP [sciencedirect]: a.download failed: %s", exc
                                    )

                                if dl_tmp.exists():
                                    dl_tmp.unlink()

                                try:
                                    logger.debug(
                                        "Chrome CDP [sciencedirect]: trying context.request GET"
                                    )
                                    response = await context.request.get(
                                        s3_url,
                                        headers={"User-Agent": _CHROME_UA},
                                        timeout=30000,
                                    )
                                    data = await response.body()
                                    content_type = response.headers.get("content-type", "")
                                    if (
                                        response.ok
                                        and len(data) > 10000
                                        and data[:4] == b"%PDF"
                                        and "application/pdf" in content_type.lower()
                                    ):
                                        dest.write_bytes(data)
                                        logger.info(
                                            "Downloaded SD PDF via authenticated request "
                                            "for %s (%d bytes)",
                                            paper.doi,
                                            len(data),
                                        )
                                        await browser.close()
                                        return dest
                                    logger.debug(
                                        "Chrome CDP [sciencedirect]: context.request "
                                        "did not return PDF (ok=%s, ct=%s, bytes=%d)",
                                        response.ok,
                                        content_type,
                                        len(data),
                                    )
                                except Exception as exc:
                                    logger.debug(
                                        "Chrome CDP [sciencedirect]: context.request failed: %s",
                                        exc,
                                    )

                    except Exception as exc:
                        logger.debug("Chrome CDP [sciencedirect]: unexpected error: %s", exc)

                # --- MDPI: citation_pdf_url -> window.open -> expect_download ---
                if publisher.name == "mdpi":
                    try:
                        cite = await page.evaluate(
                            "() => document.querySelector("
                            "'meta[name=\"citation_pdf_url\"]'"
                            ")?.content"
                        )
                        if not cite:
                            logger.debug("Chrome CDP [mdpi]: no citation_pdf_url")
                            await browser.close()
                            return None

                        try:
                            # Clean up any leftover file from a previous run.
                            if dest.exists():
                                dest.unlink()

                            # Use <a download> to trigger a real download event
                            # instead of window.location.href which opens inline PDF.
                            async with page.expect_download(timeout=30000) as di:
                                await page.evaluate(
                                    """(url) => {
                                        const a = document.createElement('a');
                                        a.href = url;
                                        a.download = '';
                                        document.body.appendChild(a);
                                        a.click();
                                        document.body.removeChild(a);
                                    }""",
                                    cite,
                                )
                            dl = await di.value
                            await dl.save_as(str(dest))
                            await asyncio.sleep(3)

                            if dest.exists() and dest.stat().st_size > 10000:
                                data = dest.read_bytes()
                                if data[:4] == b"%PDF":
                                    logger.info(
                                        "Downloaded MDPI PDF via Chrome CDP for %s (%d bytes)",
                                        paper.doi,
                                        len(data),
                                    )
                                    await browser.close()
                                    return dest
                        except Exception as exc:
                            logger.debug("Chrome CDP [mdpi]: <a download> failed: %s", exc)
                            # Fallback: fetch the PDF URL directly via httpx
                            try:
                                import httpx

                                async with httpx.AsyncClient(timeout=30) as client:
                                    resp = await client.get(cite, follow_redirects=True)
                                    if resp.status_code == 200 and resp.content[:4] == b"%PDF":
                                        dest.write_bytes(resp.content)
                                        logger.info(
                                            "Downloaded MDPI PDF via httpx fallback "
                                            "for %s (%d bytes)",
                                            paper.doi,
                                            _pdf_byte_count(resp.content),
                                        )
                                        await browser.close()
                                        return dest
                            except Exception as exc2:
                                logger.debug(
                                    "Chrome CDP [mdpi]: httpx fallback also failed: %s",
                                    exc2,
                                )
                        await browser.close()
                        return None

                    except Exception as exc:
                        logger.debug("Chrome CDP [mdpi]: unexpected error: %s", exc)
                        await browser.close()
                        return None

                # --- ACS: PDF URL navigation ---
                if publisher.name == "acs":
                    try:
                        pdf_url = f"https://pubs.acs.org/doi/pdf/{paper.doi}"
                        logger.debug("Chrome CDP [acs]: navigating to PDF URL")
                        try:
                            await page.goto(pdf_url, wait_until="load", timeout=30000)
                            await asyncio.sleep(3)
                        except Exception:
                            pass
                        ct = ""
                        with contextlib.suppress(Exception):
                            ct = await page.evaluate("document.contentType")
                        current_url = page.url
                        if ct == "application/pdf" or current_url.rstrip("/").endswith(".pdf"):
                            for _ in range(10):
                                if pdf_data:
                                    break
                                await asyncio.sleep(1)
                            if not pdf_data:
                                dl_tmp = dest.with_name(dest.name + ".tmp")
                                if dl_tmp.exists():
                                    dl_tmp.unlink()
                                try:
                                    async with page.expect_download(timeout=30000) as di:
                                        await page.evaluate(
                                            """(url) => {
                                                const a = document.createElement('a');
                                                a.href = url; a.download = '';
                                                document.body.appendChild(a); a.click();
                                                document.body.removeChild(a);
                                            }""",
                                            current_url,
                                        )
                                    dl = await di.value
                                    await dl.save_as(str(dl_tmp))
                                    await asyncio.sleep(2)
                                    if dl_tmp.exists() and dl_tmp.stat().st_size > 10000:
                                        data = dl_tmp.read_bytes()
                                        if data[:4] == b"%PDF":
                                            if dest.exists():
                                                dest.unlink()
                                            dl_tmp.rename(dest)
                                            pdf_data = data
                                            logger.info(
                                                "Downloaded ACS PDF via Chrome CDP "
                                                "for %s (%d bytes)",
                                                paper.doi,
                                                len(data),
                                            )
                                except Exception:
                                    pass
                                if dl_tmp.exists():
                                    dl_tmp.unlink()
                    except Exception as exc:
                        logger.debug("Chrome CDP [acs]: error: %s", exc)
                    if pdf_data:
                        await browser.close()
                    else:
                        logger.debug(
                            "Chrome CDP [acs]: no PDF captured, fall through to generic handler"
                        )

                # --- Taylor & Francis: click "View PDF" on article page ---
                if publisher.name == "taylor_francis":
                    try:
                        logger.debug(
                            "Chrome CDP [taylor_francis]: searching for "
                            "View PDF link on article page"
                        )

                        # Find PDF link using Playwright locator (valid CSS).
                        pdf_loc = None
                        selectors = [
                            'a[href*="/doi/pdf/"]',
                            'a[href*=".pdf"]',
                            "a.show-pdf-link",
                            'a[data-download="pdf"]',
                        ]
                        for sel in selectors:
                            loc = page.locator(sel).first
                            if await loc.count() > 0 and await loc.is_visible():
                                pdf_loc = loc
                                break

                        if pdf_loc:
                            href = await pdf_loc.get_attribute("href")
                            logger.debug(
                                "Chrome CDP [taylor_francis]: found PDF link: %s",
                                href[:100] if href else "(no href)",
                            )
                            # Click it — may navigate page or trigger download.
                            try:
                                await pdf_loc.click()
                                logger.debug(
                                    "Chrome CDP [taylor_francis]: clicked, waiting for page..."
                                )
                                await asyncio.sleep(3)
                                # Wait for navigation / PDF to load.
                                for _ in range(20):
                                    if pdf_data:
                                        break
                                    await asyncio.sleep(1)
                            except Exception as exc:
                                logger.debug("Chrome CDP [taylor_francis]: click error: %s", exc)
                        else:
                            logger.debug(
                                "Chrome CDP [taylor_francis]: no View PDF link "
                                "found on article page"
                            )

                        if not pdf_data:
                            logger.debug(
                                "Chrome CDP [taylor_francis]: no PDF captured, current URL: %s",
                                page.url[:120],
                            )
                    except Exception as exc:
                        logger.debug("Chrome CDP [taylor_francis]: error: %s", exc)

                    # Fall through to generic handler regardless.
                    # printToPDF at step 8 will be our last resort.

                # 7. Interact with the page to trigger PDF download.
                if skip_generic_pdf_interaction:
                    logger.debug(
                        "Chrome CDP [%s]: skipping generic PDF interaction and preserving "
                        "article page for rendered fallback",
                        publisher.name,
                    )
                elif publisher.pdf_opens_popup:
                    # Pattern A: button opens new popup (ScienceDirect).
                    pdf_btn = page.locator(publisher.pdf_button_selector)
                    if await pdf_btn.count() == 0:
                        logger.debug(
                            "Chrome CDP [%s]: no PDF button %r",
                            publisher.name,
                            publisher.pdf_button_selector,
                        )
                        await browser.close()
                        return None

                    try:
                        async with context.expect_page(timeout=20000) as popup_info:
                            await pdf_btn.first.click()
                    except Exception as exc:
                        logger.debug(
                            "Chrome CDP [%s]: button click failed: %s",
                            publisher.name,
                            exc,
                        )
                        await browser.close()
                        return None

                    await popup_info.value
                    logger.debug("Chrome CDP [%s]: popup opened, waiting for PDF", publisher.name)

                    # Wait for PDF response (captured by global listener).
                    for _ in range(publisher.pdf_wait_timeout):
                        if pdf_data:
                            break
                        await asyncio.sleep(1)

                elif publisher.pdf_button_selector:
                    # Pattern B: known selector, same-page download.
                    pdf_btn = page.locator(publisher.pdf_button_selector)
                    if await pdf_btn.count() == 0:
                        logger.debug(
                            "Chrome CDP [%s]: no PDF button %r",
                            publisher.name,
                            publisher.pdf_button_selector,
                        )
                        await browser.close()
                        return None

                    try:
                        dl_tmp = dest.with_name(dest.name + ".tmp")
                        if dl_tmp.exists():
                            dl_tmp.unlink()
                        async with context.expect_download(timeout=30000) as download_info:
                            await pdf_btn.first.click()
                        download = await download_info.value
                        await download.save_as(str(dl_tmp))
                        await asyncio.sleep(1)
                        if dl_tmp.exists() and dl_tmp.stat().st_size > 10000:
                            data = dl_tmp.read_bytes()
                            if data[:4] == b"%PDF":
                                pdf_data = data
                        if dl_tmp.exists():
                            dl_tmp.unlink()
                    except Exception as exc:
                        logger.debug(
                            "Chrome CDP [%s]: download click failed: %s",
                            publisher.name,
                            exc,
                        )

                else:
                    # Pattern C: no known selector — try generic PDF link
                    # finder via JS. Many publishers expose a visible
                    # "Download PDF" or "View PDF" link; click the first
                    # one found on the page.
                    try:
                        clicked = await page.evaluate(
                            """() => {
                            const selectors = [
                                'a[href*=".pdf"]',
                                'a[href*="/pdf"]',
                                'a[href*="download"]',
                                'a[href*="Download"]',
                                '[class*="pdf"] a',
                                '[class*="PDF"] a',
                                'a.pdf-download',
                                'a.PDF-download',
                                '.pdf-btn a',
                                '.article__pdf a',
                                '[data-download="pdf"]',
                            ];
                            for (const sel of selectors) {
                                const els = document.querySelectorAll(sel);
                                for (const el of els) {
                                    if (el.offsetParent !== null) {
                                        el.click();
                                        return true;
                                    }
                                }
                            }
                            return false;
                        }"""
                        )
                        if clicked:
                            logger.debug(
                                "Chrome CDP [%s]: generic PDF link clicked",
                                publisher.name,
                            )

                        # Wait for PDF response (captured by global listener).
                        for _ in range(publisher.pdf_wait_timeout):
                            if pdf_data:
                                break
                            await asyncio.sleep(1)

                        # If the generic click didn't trigger a PDF, also
                        # try navigating directly to any PDF link found.
                        if not pdf_data:
                            pdf_href = await page.evaluate(
                                """() => {
                                const links = document.querySelectorAll(
                                    'a[href*=".pdf"], a[href*="/pdf"]'
                                );
                                for (const el of links) {
                                    if (el.offsetParent !== null && el.href) {
                                        return el.href;
                                    }
                                }
                                return null;
                            }"""
                            )
                            if pdf_href:
                                logger.debug(
                                    "Chrome CDP [%s]: navigating to PDF link %s",
                                    publisher.name,
                                    pdf_href,
                                )
                                with contextlib.suppress(Exception):
                                    await page.goto(
                                        pdf_href,
                                        wait_until="networkidle",
                                        timeout=15000,
                                    )
                    except Exception as pattern_exc:
                        logger.debug(
                            "Chrome CDP [%s]: Pattern C error (%s), waiting for page to settle",
                            publisher.name,
                            pattern_exc,
                        )
                        # Page may have navigated (e.g. OIDC redirect).
                        # Wait for it to settle before printToPDF.
                        with contextlib.suppress(Exception):
                            await page.wait_for_load_state("networkidle", timeout=30000)

                # If a generic PDF click navigated us away from the article
                # page (e.g. inline viewer / error page) without capturing a
                # PDF, go back so printToPDF renders the full article text.
                if not pdf_data and article_page_url and page.url != article_page_url:
                    # The click may have landed on ScienceDirect's cfts/init
                    # (Cloudflare Turnstile + token handshake) page. That flow
                    # needs 10-60s for the invisible challenge to complete
                    # before the real PDF streams in — DO NOT restore the
                    # article page immediately or the handshake is aborted.
                    _landed = page.url
                    if "cfts/init" in _landed or "turnstile" in _landed or "challenge" in _landed:
                        logger.debug(
                            "Chrome CDP [%s]: on challenge handshake page %s — "
                            "waiting for Turnstile to complete",
                            publisher.name,
                            _landed[:80],
                        )
                        # Revenue-trial approach for Turnstile:
                        #   1. click a visible checkbox if present
                        #   2. wait for the token (hidden input / API)
                        #   3. actively invoke the page's formSubmit() once the
                        #      token is ready — the cfts/init page only streams
                        #      the real PDF after that submit.
                        for _turn in range(75):  # up to ~75s
                            if pdf_data:
                                break
                            _ct = await page.evaluate("document.contentType")
                            if _ct == "application/pdf":
                                break
                            # 1. click visible Turnstile checkbox (idempotent)
                            with contextlib.suppress(Exception):
                                _box = page.locator(
                                    ".cf-turnstile, #cf-turnstile, iframe[src*='turnstile']"
                                )
                                if await _box.count() >= 1:
                                    await _box.first.click(timeout=2000)
                            # 2. check whether the token is ready
                            _ready = False
                            with contextlib.suppress(Exception):
                                _ready = await page.evaluate(
                                    """() => {
                                        const hidden = document.querySelector(
                                            'input[name="cf-turnstile-response"]');
                                        if (hidden && hidden.value) return true;
                                        if (typeof window.turnstile !== 'undefined') {
                                            try {
                                                const api = window.turnstile;
                                                if (typeof api.getResponse === 'function'
                                                    && api.getResponse()) return true;
                                            } catch (e) {}
                                        }
                                        if (window.turnstileComplete === true) return true;
                                        return false;
                                    }"""
                                )
                            if _ready:
                                # 3. actively submit the cfts form
                                with contextlib.suppress(Exception):
                                    await page.evaluate(
                                        """() => {
                                            if (typeof formSubmit === 'function') {
                                                formSubmit();
                                                return true;
                                            }
                                            const f = document.getElementById('form1');
                                            if (f) {
                                                f.submit();
                                                return true;
                                            }
                                            return false;
                                        }"""
                                    )
                                for _ in range(30):  # up to ~30s after submit
                                    if pdf_data:
                                        break
                                    _ct = await page.evaluate("document.contentType")
                                    if _ct == "application/pdf":
                                        break
                                    await asyncio.sleep(1)
                                if pdf_data or _ct == "application/pdf":
                                    break
                            await asyncio.sleep(1)
                        if pdf_data and pdf_data[:4] == b"%PDF":
                            dest.write_bytes(pdf_data)
                            logger.info(
                                "Downloaded PDF via Chrome CDP after Turnstile for %s (%d bytes)",
                                paper.doi,
                                len(pdf_data),
                            )
                            await browser.close()
                            return dest
                        if _ct == "application/pdf":
                            # PDF navigated into the tab; capture via CDP.
                            with contextlib.suppress(Exception):
                                cdp_session = await context.new_cdp_session(page)
                                result = await cdp_session.send(
                                    "Page.printToPDF",
                                    {
                                        "printBackground": True,
                                        "preferCSSPageSize": True,
                                    },
                                )
                                import base64

                                raw = base64.b64decode(result["data"])
                                if len(raw) > 5000 and raw[:4] == b"%PDF":
                                    dest.write_bytes(raw)
                                    logger.info(
                                        "Downloaded PDF via cfts navigation for %s (%d bytes)",
                                        paper.doi,
                                        len(raw),
                                    )
                                    await browser.close()
                                    return dest
                    logger.debug(
                        "Chrome CDP [%s]: PDF click moved page to %s, restoring article page",
                        publisher.name,
                        page.url[:80],
                    )
                    with contextlib.suppress(Exception):
                        await page.goto(
                            article_page_url,
                            wait_until="domcontentloaded",
                            timeout=30000,
                        )
                        await asyncio.sleep(3)

                # 8. CDP printToPDF fallback if nothing was captured.
                allow_rendered_fallback = _should_use_print_to_pdf_fallback(publisher) or (
                    publisher.name == "sciencedirect" and allow_sciencedirect_rendered_fallback
                )
                if not pdf_data and allow_rendered_fallback:
                    page_text = ""
                    with contextlib.suppress(Exception):
                        page_text = (
                            f"{await page.title()}\n{await page.locator('body').inner_text()}"
                        )

                    if not _text_looks_like_article_page(page_text, paper):
                        logger.debug(
                            "Chrome CDP [%s]: current page does not look like article content, "
                            "skipping printToPDF fallback",
                            publisher.name,
                        )
                    else:
                        logger.debug(
                            "Chrome CDP [%s]: no PDF captured, trying printToPDF fallback",
                            publisher.name,
                        )
                        for attempt in range(2):
                            try:
                                cdp = await context.new_cdp_session(page)
                                result = await cdp.send(
                                    "Page.printToPDF",
                                    {
                                        "printBackground": True,
                                        "preferCSSPageSize": True,
                                        "marginTop": 0.4,
                                        "marginBottom": 0.4,
                                        "marginLeft": 0.4,
                                        "marginRight": 0.4,
                                    },
                                )
                                import base64

                                raw = base64.b64decode(result["data"])
                                if (
                                    len(raw) > 5000
                                    and raw[:4] == b"%PDF"
                                    and not _rendered_pdf_looks_like_challenge(raw)
                                ):
                                    pdf_data = raw
                                    break
                                if _rendered_pdf_looks_like_challenge(raw):
                                    logger.debug(
                                        "Chrome CDP [%s]: rejecting rendered challenge PDF",
                                        publisher.name,
                                    )
                            except Exception as exc:
                                logger.debug(
                                    "Chrome CDP [%s]: printToPDF attempt %d error: %s",
                                    publisher.name,
                                    attempt + 1,
                                    exc,
                                )
                                # One retry with a short delay
                                await asyncio.sleep(2)

                await browser.close()

            # 9. Save PDF if successfully captured.
            if pdf_data and pdf_data[:4] == b"%PDF":
                dest.write_bytes(pdf_data)
                logger.info("Downloaded PDF via Chrome CDP (%s) for %s", publisher.name, paper.doi)
                return dest

            logger.debug("Chrome CDP [%s]: no PDF captured", publisher.name)
            return None

        except Exception as exc:
            logger.debug("Chrome CDP [%s]: unexpected error: %s", publisher.name, exc)
            return None

        finally:
            # Cleanup: kill Chrome process tree and remove temp directory.
            if chrome_proc:
                try:
                    kill_process_tree(chrome_proc)
                except Exception:
                    try:
                        chrome_proc.kill()
                        chrome_proc.wait(timeout=5)
                    except Exception:
                        pass
            # Keep the persistent Chrome profile directory so Cloudflare
            # clearance cookies survive across downloads.
