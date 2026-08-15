"""Downloader for publisher-direct PDF links.

Attempts to follow ``paper.pdf_url`` if set. As a fallback, generates
known direct-PDF URLs from the DOI for matching publishers, then falls back
to following the DOI URL and extracting ``citation_pdf_url`` from HTML.
This handles OA publishers like MDPI and Frontiers whose PDF URLs can't
be derived from the DOI alone.
"""

from __future__ import annotations

import html
import logging
import re
from pathlib import Path
from urllib.parse import unquote, urljoin

import httpx

from litkit.core.models import Paper
from litkit.core.ratelimit import bucket_for
from litkit.downloaders.base import Downloader

logger = logging.getLogger(__name__)

_MDPI_DOI_PREFIX = "10.3390/"

# MDPI DOI journal abbreviation → mdpi-res CDN path slug.
# MDPI article DOIs use a short journal abbreviation (e.g. ``nu`` for
# Nutrients, ``polym`` for Polymers), while the CDN paths use the full
# lowercase journal name.  Journals not listed fall back to the
# abbreviation itself (e.g. foods, ijms, molecules all match directly).
_MDPI_JOURNAL_NAMES: dict[str, str] = {
    "nu": "nutrients",
    "su": "sustainability",
    "en": "energies",
    "s": "sensors",
    "ma": "materials",
    "pr": "processes",
    "md": "marinedrugs",
    "mi": "micromachines",
    "polym": "polymers",
    "app": "applsci",
    "bios": "biosensors",
    "ijerph": "ijerph",
    "applsci": "applsci",
    "biomedicines": "biomedicines",
    "jcm": "jcm",
    "jpm": "jpm",
    "remotesensing": "remotesensing",
    "jmse": "jmse",
    "jof": "jof",
    "jfb": "jfb",
    "cancers": "cancers",
    "cells": "cells",
    "molecules": "molecules",
    "pharmaceutics": "pharmaceutics",
    "biomolecules": "biomolecules",
    "antioxidants": "antioxidants",
    "catalysts": "catalysts",
    "antibiotics": "antibiotics",
    "vaccines": "vaccines",
    "viruses": "viruses",
    "microorganisms": "microorganisms",
    "nanomaterials": "nanomaterials",
    "electronics": "electronics",
    "photonics": "photonics",
    "metals": "metals",
    "coatings": "coatings",
    "crystals": "crystals",
    "water": "water",
    "forests": "forests",
    "plants": "plants",
    "agronomy": "agronomy",
    "animals": "animals",
    "agriculture": "agriculture",
    "genes": "genes",
    "diagnostics": "diagnostics",
    "healthcare": "healthcare",
    "life": "life",
    "biology": "biology",
    "toxins": "toxins",
    "symmetry": "symmetry",
    "mathematics": "mathematics",
    "entropy": "entropy",
    "machines": "machines",
    "actuators": "actuators",
    "robotics": "robotics",
    "systems": "systems",
    "drones": "drones",
    "buildings": "buildings",
    "land": "land",
    "insects": "insects",
    "membranes": "membranes",
    "biosensors": "biosensors",
    "chemosensors": "chemosensors",
    "separations": "separations",
    "gel": "gels",
}


def _mdpi_res_urls(doi: str) -> list[str]:
    """Return mdpi-res.com CDN PDF URLs derived from an MDPI DOI.

    MDPI blocks non-browser HTTP clients on ``www.mdpi.com`` (HTTP 403),
    but serves the same PDFs from the ``mdpi-res.com`` CDN using a
    predictable pattern::

        {abbr}{vol:02}{issue:02}{article:05}  (DOI digit layout)
        -> {journal}-{vol:02}-{article:05}    (CDN path)

    Example: ``10.3390/nu14030588`` → journal ``nutrients``, volume 14,
    article 588 → ``https://mdpi-res.com/d_attachment/nutrients/``
    ``nutrients-14-00588/article_deploy/nutrients-14-00588.pdf``.

    Returns ``[]`` when the DOI cannot be parsed as an MDPI DOI.
    """
    if not (doi or "").lower().startswith(_MDPI_DOI_PREFIX):
        return []
    suffix = doi.split("/", 1)[1].strip()
    # Journal abbreviation is the leading alpha run; the rest is digits
    # in fixed 2-digit volume + 2-digit issue + variable-width article.
    match = re.match(r"([A-Za-z]+)(\d+)$", suffix)
    if not match:
        return []
    abbr = match.group(1).lower()
    digits = match.group(2)
    if len(digits) < 4:
        return []
    try:
        vol = int(digits[:2])
        issue = int(digits[2:4])
        article = int(digits[4:])
    except ValueError:
        return []
    if vol <= 0 or issue <= 0 or article <= 0:
        return []
    name = _MDPI_JOURNAL_NAMES.get(abbr, abbr)
    stem = f"{name}-{vol:02d}-{article:05d}"
    return [
        f"https://mdpi-res.com/d_attachment/{name}/{stem}/article_deploy/{stem}.pdf"
    ]


_PUBLISHER_PATTERN_RULES: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    (
        ("10.1007/", "10.1617/"),
        (
            "https://link.springer.com/content/pdf/{doi}.pdf",
            "https://link.springer.com/content/pdf/{doi_path}.pdf",
        ),
    ),
    (("10.1002/", "10.1111/"), ("https://onlinelibrary.wiley.com/doi/pdf/{doi}",)),
    (("10.1080/", "10.1201/"), ("https://www.tandfonline.com/doi/pdf/{doi}",)),
    (("10.1177/",), ("https://journals.sagepub.com/doi/pdf/{doi}",)),
    (("10.1038/",), ("https://www.nature.com/articles/{doi_path}.pdf",)),
    (("10.1126/",), ("https://www.science.org/doi/pdf/{doi}",)),
    (("10.1016/",), ("https://www.sciencedirect.com/science/article/pii/{doi_path}/pdf",)),
    (("10.1515/",), ("https://www.degruyter.com/document/doi/{doi}/pdf",)),
    (("10.3390/",), ("https://www.mdpi.com/{doi_path}/pdf",)),
    (("10.3389/",), ("https://www.frontiersin.org/journals/{doi_path}/pdf",)),
    (("10.1021/",), ("https://pubs.acs.org/doi/pdf/{doi}",)),
    (
        ("10.1039/",),
        ("https://pubs.rsc.org/en/content/articlepdf/{year}/FO/{doi_path_upper}",),
    ),
]

_CITATION_PDF_RE = re.compile(
    r'<meta\s+name=[\'"]citation_pdf_url[\'"]\s+content=[\'"]([^\'"]+)[\'"]',
    re.IGNORECASE,
)

_PDF_HREF_RE = re.compile(r'href=[\'"]([^\'"]*pdf[^\'"]*)[\'"]', re.IGNORECASE)
_META_REFRESH_RE = re.compile(
    r'<meta[^>]+http-equiv=[\'"]refresh[\'"][^>]+content=[\'"][^\'"]*url=([^\'">]+)',
    re.IGNORECASE,
)
_REDIRECT_INPUT_RE = re.compile(
    r'<input[^>]+id=[\'"]redirectURL[\'"][^>]+value=[\'"]([^\'"]+)[\'"]',
    re.IGNORECASE,
)


def _candidate_pdf_urls(paper: Paper) -> list[str]:
    """Return direct-PDF candidates based on known DOI prefix rules."""
    doi = paper.doi or ""
    doi_path = doi.split("/", 1)[-1] if "/" in doi else doi
    doi_path_upper = doi_path.upper()
    year = str(paper.year) if paper.year else ""

    # MDPI blocks www.mdpi.com for non-browser clients (403); prefer the
    # predictable mdpi-res.com CDN links, keeping the HTML page as backup.
    if doi.lower().startswith(_MDPI_DOI_PREFIX):
        return _mdpi_res_urls(doi) + [
            f"https://www.mdpi.com/{doi_path}/pdf"
        ]

    for prefixes, patterns in _PUBLISHER_PATTERN_RULES:
        if doi.startswith(prefixes):
            return [
                pattern.format(
                    doi=doi,
                    doi_path=doi_path,
                    doi_path_upper=doi_path_upper,
                    year=year,
                )
                for pattern in patterns
            ]
    return []


def _extract_pdf_candidates(base_url: str, html_text: str) -> list[str]:
    """Extract likely PDF URLs from HTML in priority order."""
    candidates: list[str] = []

    match = _CITATION_PDF_RE.search(html_text)
    if match:
        candidates.append(urljoin(base_url, match.group(1)))

    for match in _PDF_HREF_RE.finditer(html_text):
        candidates.append(urljoin(base_url, html.unescape(match.group(1))))

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        deduped.append(candidate)
    return deduped


def _extract_follow_url(base_url: str, html_text: str) -> str | None:
    """Extract a follow-up article URL from HTML redirect stubs."""
    match = _META_REFRESH_RE.search(html_text)
    if match:
        raw = match.group(1).strip().strip("'\"")
        return urljoin(base_url, html.unescape(raw))

    match = _REDIRECT_INPUT_RE.search(html_text)
    if match:
        raw = html.unescape(match.group(1))
        return urljoin(base_url, unquote(raw))

    return None


class PublisherDirectDownloader(Downloader):
    """Download PDFs from publisher direct URLs."""

    name = "publisher_direct"

    async def can_handle(self, paper: Paper) -> bool:
        return bool(paper.doi)

    async def download(self, paper: Paper) -> Path | None:
        if not paper.doi:
            return None

        dest = self._cache.pdf_path(paper.id)
        dest.parent.mkdir(parents=True, exist_ok=True)

        if paper.pdf_url:
            bucket = bucket_for("publisher_direct")
            await bucket.acquire()
            result = await self._fetch_and_save(paper.pdf_url, dest)
            if result is not None:
                return result

        doi_path = paper.doi.split("/", 1)[-1] if "/" in paper.doi else paper.doi
        for url in _candidate_pdf_urls(paper):
            bucket = bucket_for("publisher_direct")
            await bucket.acquire()
            result = await self._fetch_and_save(url, dest)
            if result is not None:
                logger.info("Downloaded %s via direct pattern: %s", paper.doi, url)
                return result

        return await self._download_via_doi_page(paper.doi, doi_path, dest)

    async def _download_via_doi_page(self, doi: str, doi_path: str, dest: Path) -> Path | None:
        """Follow the DOI URL, parse HTML for ``citation_pdf_url``, download."""
        del doi_path
        doi_url = self._cache.get_doi_resolution(doi) or f"https://doi.org/{doi}"
        return await self._download_from_landing_page(doi, doi_url, dest)

    async def _download_from_landing_page(
        self,
        doi: str,
        page_url: str,
        dest: Path,
        *,
        depth: int = 0,
    ) -> Path | None:
        """Fetch a landing page, follow one redirect stub, and extract PDF links."""
        bucket = bucket_for("publisher_direct")
        await bucket.acquire()

        try:
            resp = await self._client.get(
                page_url,
                follow_redirects=True,
                timeout=httpx.Timeout(15.0),
            )
            resp.raise_for_status()
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            logger.debug(
                "Publisher direct landing-page error for %s via %s: %s",
                doi,
                page_url,
                exc,
            )
            return None

        self._cache.put_doi_resolution(doi, str(resp.url))

        ct = resp.headers.get("content-type", "")
        if "application/pdf" in ct:
            dest.write_bytes(resp.content)
            return dest

        if "text/html" not in ct:
            return None

        html_text = resp.text
        for pdf_url in _extract_pdf_candidates(str(resp.url), html_text):
            result = await self._fetch_and_save(pdf_url, dest)
            if result is not None:
                return result

        if depth >= 2:
            logger.debug("No downloadable PDF links found on article page for %s", doi)
            return None

        follow_url = _extract_follow_url(str(resp.url), html_text)
        if follow_url and follow_url != str(resp.url):
            return await self._download_from_landing_page(doi, follow_url, dest, depth=depth + 1)

        logger.debug("No downloadable PDF links found on article page for %s", doi)
        return None

    async def _fetch_and_save(self, url: str, dest: Path) -> Path | None:
        """GET *url* and, if the response is a PDF, write to *dest*."""
        try:
            response = await self._client.get(
                url,
                follow_redirects=True,
                timeout=httpx.Timeout(10.0),
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.debug("Publisher direct HTTP %s for %s", exc.response.status_code, url)
            return None
        except httpx.RequestError as exc:
            logger.debug("Publisher direct request error for %s: %s", url, exc)
            return None

        ct = response.headers.get("content-type", "")
        if "application/pdf" in ct or "application/octet-stream" in ct:
            dest.write_bytes(response.content)
            return dest

        if "text/html" in ct:
            logger.debug("Publisher direct URL %s returned HTML (not PDF), skipping", url)
            return None

        logger.debug(
            "Publisher direct URL %s returned unexpected Content-Type: %s",
            url,
            ct,
        )
        return None
