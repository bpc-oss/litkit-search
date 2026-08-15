"""Chinese literature downloader with SZU/institution-friendly fallbacks."""

from __future__ import annotations

import http.cookiejar as cookiejar
import logging
import re
from pathlib import Path
from urllib.parse import urljoin

import httpx

from litkit.chinese.acquisition import append_acquisition_request, request_from_paper
from litkit.core.models import Paper
from litkit.core.ratelimit import bucket_for
from litkit.downloaders.base import Downloader

logger = logging.getLogger(__name__)

_CHINESE_PROVIDERS = {"cnki", "wanfang", "cqvip", "sinomed", "ncpssd", "szu_library"}
_META_PDF_RE = re.compile(
    r'<meta\s[^>]*name\s*=\s*["\']citation_pdf_url["\'][^>]*'
    r'content\s*=\s*["\'](?P<url>[^"\']+)["\']',
    re.IGNORECASE,
)
_A_PDF_RE = re.compile(
    r'<a\s[^>]*href\s*=\s*["\'](?P<url>[^"\']+\.pdf[^"\']*)["\']',
    re.IGNORECASE,
)


class ChineseInstitutionalDownloader(Downloader):
    """Download Chinese PDFs only through explicit URLs or institutional access.

    CNKI/Wanfang/CQVIP access often depends on SZU unified authentication or
    on-campus IP. When no direct PDF can be resolved, this downloader records a
    CSV acquisition request instead of retrying aggressively.
    """

    name = "chinese_institutional"

    def __init__(self, cache, config):
        super().__init__(cache, config)
        self._proxy_url = getattr(config, "institutional_proxy", "").strip()
        self._direct = bool(getattr(config, "institutional_direct", False))
        self._queue_path = getattr(config, "chinese_acquisition_queue", "")

        cookie_file = getattr(config, "institutional_cookie_file", "")
        if cookie_file:
            self._load_cookie_file(Path(cookie_file))

    async def can_handle(self, paper: Paper) -> bool:
        provider = str(paper.extra.get("provider", "")).lower()
        resource = str(paper.extra.get("resource", "")).lower()
        return (
            paper.language == "zh"
            or paper.source in _CHINESE_PROVIDERS
            or provider in _CHINESE_PROVIDERS
            or resource in _CHINESE_PROVIDERS
        )

    async def download(self, paper: Paper) -> Path | None:
        dest = self._cache.pdf_path(paper.id)
        dest.parent.mkdir(parents=True, exist_ok=True)

        urls = [u for u in (paper.pdf_url, paper.source_url) if u]
        for url in urls:
            bucket = bucket_for("chinese_institutional")
            await bucket.acquire()
            result = await self._try_url(self._proxify(url), dest)
            if result is not None:
                return result

        queue_path = append_acquisition_request(
            request_from_paper(paper),
            self._queue_path or None,
        )
        self._cache.audit("chinese_acquisition_queue", f"{paper.id} -> {queue_path}")
        return None

    def _proxify(self, url: str) -> str:
        if self._proxy_url and not self._direct:
            return f"{self._proxy_url}{url}"
        return url

    def _load_cookie_file(self, path: Path) -> None:
        if not path.exists():
            logger.warning("Cookie file not found: %s", path)
            return
        try:
            jar = cookiejar.MozillaCookieJar()
            jar.load(str(path), ignore_discard=True, ignore_expires=True)
            for cookie in jar:
                self._client.cookies.set(
                    cookie.name,
                    cookie.value,
                    domain=cookie.domain,
                    path=cookie.path,
                )
        except Exception as exc:
            logger.warning("Failed to load Chinese institutional cookies from %s: %s", path, exc)

    async def _try_url(self, url: str, dest: Path) -> Path | None:
        try:
            response = await self._client.get(
                url,
                follow_redirects=True,
                timeout=httpx.Timeout(20.0),
            )
            response.raise_for_status()
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            logger.debug("Chinese institutional request failed for %s: %s", url, exc)
            return None

        content_type = response.headers.get("content-type", "").lower()
        if "application/pdf" in content_type or response.content[:4] == b"%PDF":
            dest.write_bytes(response.content)
            return dest

        if "text/html" not in content_type:
            return None

        pdf_url = self._extract_pdf_url(response.text, str(response.url))
        if not pdf_url:
            return None

        try:
            pdf_response = await self._client.get(
                self._proxify(pdf_url),
                follow_redirects=True,
                timeout=httpx.Timeout(20.0),
            )
            pdf_response.raise_for_status()
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            logger.debug("Chinese institutional PDF link failed for %s: %s", pdf_url, exc)
            return None

        if (
            "application/pdf" in pdf_response.headers.get("content-type", "").lower()
            or pdf_response.content[:4] == b"%PDF"
        ):
            dest.write_bytes(pdf_response.content)
            return dest
        return None

    def _extract_pdf_url(self, html: str, base_url: str) -> str | None:
        if match := _META_PDF_RE.search(html):
            return urljoin(base_url, match.group("url"))
        for match in _A_PDF_RE.finditer(html):
            url = match.group("url")
            if not url.startswith(("javascript:", "data:")):
                return urljoin(base_url, url)
        return None
