"""Download PDFs from Library Genesis mirrors.

New-generation mirrors (libgen.gl/.vg/.la/.bz) use an ``index.php``-based
search with a multi-step download flow::

    search (index.php) → edition page → ads page → get.php → CDN → PDF
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import httpx

from litkit.core.models import Paper
from litkit.downloaders._dns import ensure_resolved
from litkit.downloaders.base import Downloader

logger = logging.getLogger(__name__)

# New-generation LibGen mirrors reachable from China.
_LIBGEN_MIRRORS = [
    "https://libgen.gl",
    "https://libgen.vg",
    "https://libgen.la",
    "https://libgen.bz",
]

# Extract edition ID from search results.
_EDITION_ID_RE = re.compile(r"edition\.php\?id=(\d+)")

# Extract MD5 hash from ads.php link on edition/file pages.
_MD5_RE = re.compile(r"/ads\.php\?md5=([a-f0-9]{32})")

# Extract the download key from the GET link on the ads page.
_GET_KEY_RE = re.compile(r"get\.php\?md5=[a-f0-9]{32}&(?:amp;)?key=([A-Z0-9]+)")


class LibgenDownloader(Downloader):
    """Download PDFs from Library Genesis."""

    name = "libgen"

    async def can_handle(self, paper: Paper) -> bool:
        return bool(paper.doi)

    async def download(self, paper: Paper) -> Path | None:
        ensure_resolved()

        if not paper.doi:
            return None

        mirrors = _LIBGEN_MIRRORS
        configured = getattr(self._config, "libgen_mirror", None)
        if configured:
            mirrors = [configured] + [m for m in _LIBGEN_MIRRORS if m != configured]

        dest = self._cache.pdf_path(paper.id)
        dest.parent.mkdir(parents=True, exist_ok=True)

        for mirror in mirrors:
            result = await self._try_mirror(mirror, paper.doi, dest)
            if result is not None:
                return result

        logger.info("All LibGen mirrors exhausted for %s", paper.doi)
        return None

    async def _try_mirror(self, mirror: str, doi: str, dest: Path) -> Path | None:
        """Multi-step download: search → edition → ads → get.php → CDN → PDF."""
        md5 = await self._resolve_md5(mirror, doi)
        if not md5:
            return None

        key = await self._resolve_download_key(mirror, md5, doi)
        if not key:
            return None

        return await self._download_pdf(mirror, md5, key, dest)

    async def _resolve_md5(self, mirror: str, doi: str) -> str | None:
        """Search for *doi* and return the first file's MD5."""
        try:
            resp = await self._client.get(
                f"{mirror}/index.php",
                params={"req": doi, "res": "25", "covers": "on", "filesuns": "all"},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError:
            logger.debug("LibGen search failed (%s)", mirror)
            return None
        except httpx.RequestError as exc:
            logger.debug("LibGen connection failed %s: %s", mirror, exc)
            return None

        # Extract the first edition ID.
        m = _EDITION_ID_RE.search(resp.text)
        if not m:
            logger.debug("No edition ID on %s for %s", mirror, doi)
            return None
        edition_id = m.group(1)

        # Fetch the edition page to get the MD5.
        try:
            edition_resp = await self._client.get(
                f"{mirror}/edition.php",
                params={"id": edition_id},
            )
            edition_resp.raise_for_status()
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            logger.debug("Edition page failed %s: %s", mirror, exc)
            return None

        m = _MD5_RE.search(edition_resp.text)
        if not m:
            logger.debug("No MD5 on edition page %s for %s", mirror, doi)
            return None
        return m.group(1)

    async def _resolve_download_key(self, mirror: str, md5: str, doi: str) -> str | None:
        """Fetch the ads page and extract the download key."""
        try:
            resp = await self._client.get(
                f"{mirror}/ads.php",
                params={"md5": md5, "downloadname": doi},
            )
            resp.raise_for_status()
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            logger.debug("Ads page failed %s: %s", mirror, exc)
            return None

        m = _GET_KEY_RE.search(resp.text)
        if not m:
            logger.debug("No download key on ads page %s for %s", mirror, doi)
            return None
        return m.group(1)

    async def _download_pdf(self, mirror: str, md5: str, key: str, dest: Path) -> Path | None:
        """Download via get.php (auto-follows 307 redirect to CDN) and save."""
        try:
            resp = await self._client.get(
                f"{mirror}/get.php",
                params={"md5": md5, "key": key},
                timeout=httpx.Timeout(120.0),
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.debug("PDF GET failed (%s) for %s", exc.response.status_code, mirror)
            return None
        except httpx.RequestError as exc:
            logger.debug("PDF GET request error %s: %s", mirror, exc)
            return None

        content_type = resp.headers.get("content-type", "")
        # LibGen CDNs return application/octet-stream for PDFs.
        if "text/html" in content_type:
            logger.debug("Resource at %s is HTML, not PDF (content-type: %s)", mirror, content_type)
            return None

        dest.write_bytes(resp.content)
        logger.info("Saved LibGen PDF for %s to %s", dest.name, dest)
        return dest
