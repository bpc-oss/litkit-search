"""Downloader for supplementary materials (data, figures, tables, etc.).

Each publisher uses different terminology: "Supplementary Material", "Supporting
Information", "Supplementary Data", "Supplemental Files", "ESI" (Electronic
Supporting Information), etc.  This downloader tries multiple strategies to find
and download all supplementary files for a given paper.

Returns a directory path containing all found files rather than a single PDF.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from litkit.browser_runtime import (
    browser_launch_args,
    default_profile_dir,
    kill_process_tree,
    resolve_browser_executable,
    spawn_process_kwargs,
)
from litkit.core.models import Paper

logger = logging.getLogger(__name__)

# Regex to match XML declarations
_XML_DECL_RE = re.compile(r"<\?xml\s+.*?\?>")

# ── Optional Playwright import (Chrome CDP fallback) ──────────────────────────

try:
    from playwright.async_api import async_playwright

    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


def _find_free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait_for_cdp(port: int, timeout: float = 15.0) -> None:
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2)
            return
        except Exception:
            await asyncio.sleep(0.5)
    raise TimeoutError(f"Chrome CDP not ready on port {port} after {timeout}s")


# ── Constants ──────────────────────────────────────────────────────────────────


# Supplementary cache root (override with LITKIT_CACHE_DIR for tests/CI).
def _cache_root() -> Path:
    import os

    base = Path(os.environ.get("LITKIT_CACHE_DIR") or Path.home() / ".litkit")
    root = base / "supplementary"
    root.mkdir(parents=True, exist_ok=True)
    return root


# Recognised supplementary file extensions
_SUPPL_EXTENSIONS: set[str] = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".zip",
    ".tar",
    ".gz",
    ".tgz",
    ".rar",
    ".7z",
    ".csv",
    ".tsv",
    ".txt",
    ".xml",
    ".json",
    ".fasta",
    ".fastq",
    ".gb",
    ".sdf",
    ".mol",
    ".pdb",
    ".tif",
    ".tiff",
    ".png",
    ".jpg",
    ".jpeg",
    ".eps",
    ".svg",
    ".mov",
    ".avi",
    ".mp4",
    ".wmv",
    ".html",
    ".htm",
    ".shtml",
}

# Regex for detecting supplementary-related links/headings
_SUPPL_RE = re.compile(
    r"(?:supplement(?:ary|al)?|supporting|additional|extended|"
    r"electronic\s*supporting|si|s\d{1,2})"
    r"(?:\s*[-_–]\s*|\s+)?"
    r"(?:material|data|file|info(?:rmation)?|table|figure|fig|"
    r"result|text|method|experiment|discussion|note|references?)",
    re.IGNORECASE,
)

# Look for section headings that contain these words
_SECTION_RE = re.compile(
    r"(?:supplement(?:ary|al)|supporting|additional|extended)\s*"
    r"(?:material|data|info)",
    re.IGNORECASE,
)

# Match <a> elements whose text or href suggests supplementary content
_ANCHOR_RE = re.compile(
    r"(?:supplement|supporting|additional|extended|ESI|S[0-9])|"
    r"(?:\.(?:zip|rar|tar|gz|csv|tsv|xlsx?|docx?|pptx?))",
    re.IGNORECASE,
)

# Publisher DOI prefix → supplementary URL template
# {doi} and {doi_path} are filled at runtime.
_PUBLISHER_SUPPL_PATTERNS: dict[str, list[str]] = {
    "10.1016/": [
        "https://www.sciencedirect.com/science/article/pii/{doi_path}/mmc1",
        "https://ars.els-cdn.com/content/image/1-s2.0-{doi_path}-mmc1.pdf",
        "https://ars.els-cdn.com/content/image/1-s2.0-{doi_path}-fx1.jpg",
        "https://ars.els-cdn.com/content/image/1-s2.0-{doi_path}-mmc1.docx",
        "https://ars.els-cdn.com/content/image/1-s2.0-{doi_path}-mmc2.docx",
        "https://ars.els-cdn.com/content/image/1-s2.0-{doi_path}-mmc1.zip",
        "https://ars.els-cdn.com/content/image/1-s2.0-{doi_path}-gr1.jpg",
        "https://ars.els-cdn.com/content/image/1-s2.0-{doi_path}-gr2.jpg",
    ],
    "10.1007/": [
        "https://link.springer.com/content/pdf/{doi_path}/ESM1.pdf",
        "https://link.springer.com/content/pdf/{doi_path}/ESM2.pdf",
        "https://static-content.springer.com/esm/art%3A{doi_encoded}/MediaObjects/{doi_path_flat}_MO_ESM1.pdf",
        "https://static-content.springer.com/esm/art%3A{doi_encoded}/MediaObjects/{doi_path_flat}_MO_ESM2.pdf",
    ],
    "10.1002/": [
        "https://onlinelibrary.wiley.com/doi/10.1002/{doi_path}/suppinfo/{doi_path}.pdf",
        "https://onlinelibrary.wiley.com/doi/10.1002/{doi_path}/suppinfo/{doi_path}.docx",
        "https://onlinelibrary.wiley.com/doi/10.1002/{doi_path}/suppinfo/{doi_path}.zip",
    ],
    "10.1080/": [
        "https://www.tandfonline.com/doi/suppl/{doi}",
        "https://www.tandfonline.com/doi/suppl/{doi}/suppl_file/{doi_path}.pdf",
    ],
    "10.3390/": [
        "https://www.mdpi.com/{doi_path}/s1",
        "https://www.mdpi.com/{doi_path}/s1.pdf",
        "https://www.mdpi.com/{doi_path}/htm",
    ],
    "10.3389/": [
        "https://www.frontiersin.org/articles/{doi}/pdf?is_supplementary=1",
        "https://www.frontiersin.org/articles/{doi}/supplementary-material",
    ],
    "10.1038/": [
        "https://www.nature.com/articles/{doi_path}.pdf?supplementary=1",
        "https://static-content.springer.com/esm/art%3A10.1038%2F{doi_path}/MediaObjects/{doi_path_flat}_MO_ESM1.pdf",
        "https://static-content.springer.com/esm/art%3A10.1038%2F{doi_path}/MediaObjects/{doi_path_flat}_MO_ESM2.pdf",
    ],
    "10.1101/": [
        "https://www.biorxiv.org/content/{doi}v{version}.supplementary-material",
    ],
    "10.1021/": [
        "https://pubs.acs.org/doi/suppl/{doi}/suppl_file/{doi_path}.pdf",
        "https://pubs.acs.org/doi/suppl/{doi}/suppl_file/{doi_path}.docx",
        "https://pubs.acs.org/doi/suppl/{doi}/suppl_file/{doi_path}.zip",
        "https://pubs.acs.org/doi/suppl/{doi}/suppl_file/{doi_path}.csv",
    ],
    "10.1073/": [
        "https://www.pnas.org/doi/suppl/{doi}",
        "https://www.pnas.org/doi/suppl/{doi}/suppl_file/{doi_path}.pdf",
        "https://www.pnas.org/doi/suppl/{doi}/suppl_file/{doi_path}.docx",
        "https://www.pnas.org/doi/suppl/{doi}/suppl_file/{doi_path}.xlsx",
    ],
}


# ── Publisher-specific supplementary config (for Chrome CDP) ─────────────────


@dataclass
class _SupplPublisherConfig:
    name: str
    doi_prefixes: tuple[str, ...]


_SUPPL_PUBLISHERS: tuple[_SupplPublisherConfig, ...] = (
    _SupplPublisherConfig(name="sciencedirect", doi_prefixes=("10.1016/",)),
    _SupplPublisherConfig(name="nature", doi_prefixes=("10.1038/",)),
    _SupplPublisherConfig(name="wiley", doi_prefixes=("10.1002/",)),
    _SupplPublisherConfig(name="springer", doi_prefixes=("10.1007/", "10.1617/")),
    _SupplPublisherConfig(name="mdpi", doi_prefixes=("10.3390/",)),
    _SupplPublisherConfig(name="frontiers", doi_prefixes=("10.3389/",)),
    _SupplPublisherConfig(name="acs", doi_prefixes=("10.1021/",)),
    _SupplPublisherConfig(name="taylor_francis", doi_prefixes=("10.1080/", "10.1201/")),
    _SupplPublisherConfig(name="sage", doi_prefixes=("10.1177/",)),
    _SupplPublisherConfig(name="pnas", doi_prefixes=("10.1073/",)),
)


def _detect_suppl_publisher(doi: str) -> _SupplPublisherConfig | None:
    if not doi:
        return None
    doi_lower = doi.lower()
    for pub in _SUPPL_PUBLISHERS:
        for prefix in pub.doi_prefixes:
            if doi_lower.startswith(prefix):
                return pub
    return None


_SUPPL_SECTION_SELECTORS: dict[str, str] = {
    "sciencedirect": "section[id$='-supplementary'], section[id*='supplementary'], "
    "div[id*='supplementary'], #supplementary-material, "
    "div.supplementary, section[class*='supplementary']",
    "nature": "section[data-track*='supplementary'], #Supplementary-Information-section, "
    "div[class*='supplementary'], #supplementary-information-section",
    "wiley": "div[class*='supporting'], section[class*='supporting'], "
    "div.section[aria-labelledby*='supporting']",
    "springer": "div[class*='ESM'], section[class*='Supplementary'], "
    "div[class*='supplementary-material']",
    "mdpi": "section[class*='supplementary'], #html-s1, div[class*='supplementary-material']",
    "frontiers": "section[class*='Supplementary'], div[class*='supplementary']",
    "acs": "div[class*='supplementary'], section[class*='supporting'], #supplementary-material",
    "taylor_francis": "div[class*='supplementary'], section[class*='supplementary']",
    "sage": "div[class*='supplementary'], section[class*='supplementary']",
    "pnas": "div[class*='supplementary'], #supplementary-materials",
}

# ── Public helpers ─────────────────────────────────────────────────────────────


def _cache_dir(paper: Paper) -> Path:
    """Return the directory for this paper's supplementary materials."""
    h = hashlib.sha256(paper.id.encode()).hexdigest()[:16]
    d = _cache_root() / h
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_cached(paper: Paper) -> bool:
    """Check if supplementary materials are already cached for this paper."""
    d = _cache_dir(paper)
    if not d.exists():
        return False
    files = [f for f in d.iterdir() if f.is_file() and f.name != ".done"]
    return len(files) > 0


def cached_path(paper: Paper) -> Path | None:
    """Return the cache directory if supplementary materials exist, else None."""
    d = _cache_dir(paper)
    if d.exists() and any(f.is_file() and f.name != ".done" for f in d.iterdir()):
        return d
    return None


# ── Helper functions ───────────────────────────────────────────────────────────


def _doi_path(doi: str) -> str:
    """Extract the path part of a DOI (everything after the first slash)."""
    return doi.split("/", 1)[-1] if "/" in doi else doi


def _safe_filename(url: str, suffix: str) -> str:
    """Derive a safe filename from a URL, always appending *suffix*."""
    parsed = urlparse(url)
    name = Path(parsed.path).name
    if not name or name == "/":
        name = f"supplement{suffix}"
    else:
        # Remove any existing extension that matches the suffix
        if name.endswith(suffix):
            name = name[: -len(suffix)]
        name += suffix
    # Replace non-alphanumeric chars (except dot/hyphen/underscore)
    name = re.sub(r"[^\w\.\-]", "_", name)
    return name


def _get_ext(url: str, content_type: str) -> str:
    """Guess file extension from URL or Content-Type."""
    parsed = urlparse(url)
    ext = Path(parsed.path).suffix.lower()
    if ext and ext in _SUPPL_EXTENSIONS:
        return ext

    ct_map = {
        "application/pdf": ".pdf",
        "application/zip": ".zip",
        "application/x-zip-compressed": ".zip",
        "application/gzip": ".gz",
        "application/x-tar": ".tar",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
        "text/csv": ".csv",
        "text/plain": ".txt",
        "application/json": ".json",
        "text/xml": ".xml",
        "application/xml": ".xml",
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/tiff": ".tiff",
        "image/svg+xml": ".svg",
    }
    for ct_key, ct_ext in ct_map.items():
        if ct_key in content_type:
            return ct_ext
    return ".bin"


def _save_response(response: httpx.Response, dest_dir: Path) -> Path | None:
    """Save a response body to *dest_dir* with an appropriate filename.

    Skips if content is identical to an already-saved file (checked by SHA-256).
    """
    url = str(response.url)
    ct = response.headers.get("content-type", "")
    ext = _get_ext(url, ct)
    filename = _safe_filename(url, ext)
    dest = dest_dir / filename
    body = response.content
    body_hash = hashlib.sha256(body).hexdigest()

    # Deduplicate: skip if identical content already exists
    for existing in dest_dir.iterdir():
        if existing.is_file() and existing.name != ".done" and existing.stat().st_size == len(body):
            try:
                h = hashlib.sha256(existing.read_bytes()).hexdigest()
                if h == body_hash:
                    logger.debug("Skipped duplicate: %s = %s", url, existing.name)
                    return existing
            except OSError:
                pass

    # Avoid overwriting existing files with different extensions
    if dest.exists():
        stem = dest.stem
        for i in range(1, 100):
            alt = dest_dir / f"{stem}_{i}{ext}"
            if not alt.exists():
                dest = alt
                break

    dest.write_bytes(body)
    return dest


# ── Downloader ─────────────────────────────────────────────────────────────────


class SupplementaryDownloader:
    """Download supplementary materials for a paper.

    Returns a directory path containing all found files.  Strategies tried:
      1. Crossref API — look for supplementary file links in metadata
      2. PubMed Central (PMC) — check PMC article page for supplementary files
      3. Publisher HTML page — follow DOI, parse HTML for supplementary anchors
      4. Known URL patterns — generate supplementary URLs from DOI for known publishers
      5. Chrome CDP — launch real Chrome to render JS-heavy publisher pages and
         extract supplementary links (bypasses Cloudflare/DataDome)

    Usage::

        sd = SupplementaryDownloader()
        result_dir = await sd.download(paper)   # → Path or None
        await sd.close()
    """

    def __init__(self, cache=None, config=None):
        from litkit.config import load_env

        self._config = config or load_env()
        # EZProxy config for off-campus access via Chrome CDP
        self._proxy_url = getattr(self._config, "institutional_proxy", "")
        self._institutional_direct = getattr(self._config, "institutional_direct", False)
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            },
        )
        self._cache = cache

    async def download(self, paper: Paper) -> Path | None:
        """Download all supplementary materials for *paper*.

        Returns the directory containing the downloaded files, or None
        if nothing could be found.
        """
        if not paper.doi:
            logger.warning("No DOI for paper %s, cannot search for supplementary", paper.id)
            return None

        dest = _cache_dir(paper)
        logger.info("Searching supplementary materials for %s → %s", paper.doi, dest)

        # Clear any partial download from a previous run
        # (keep existing cached files)
        found_any = False

        # Strategy 1: Crossref API
        try:
            count = await self._crossref_lookup(paper.doi, dest)
            if count > 0:
                logger.info("Crossref: found %d supplementary files for %s", count, paper.doi)
                found_any = True
        except Exception:
            logger.debug("Crossref lookup failed for %s", paper.doi, exc_info=True)

        # Strategy 2: PMC (PubMed Central)
        try:
            count = await self._pmc_lookup(paper.doi, dest)
            if count > 0:
                logger.info("PMC: found %d supplementary files for %s", count, paper.doi)
                found_any = True
        except Exception:
            logger.debug("PMC lookup failed for %s", paper.doi, exc_info=True)

        # Strategy 3: Publisher HTML page
        if not found_any:
            try:
                count = await self._parse_publisher_page(paper.doi, dest)
                if count > 0:
                    logger.info(
                        "Publisher page: found %d supplementary files for %s",
                        count,
                        paper.doi,
                    )
                    found_any = True
            except Exception:
                logger.debug("Publisher page parse failed for %s", paper.doi, exc_info=True)

        # Strategy 4: Known URL patterns
        try:
            count = await self._common_patterns(paper.doi, dest)
            if count > 0:
                logger.info("Patterns: found %d supplementary files for %s", count, paper.doi)
                found_any = True
        except Exception:
            logger.debug("Pattern-based lookup failed for %s", paper.doi, exc_info=True)

        # Strategy 5: Chrome CDP fallback (bypasses Cloudflare/DataDome)
        if not found_any:
            try:
                count = await self._chrome_cdp_strategy(paper, dest)
                if count > 0:
                    logger.info(
                        "Chrome CDP: found %d supplementary files for %s",
                        count,
                        paper.doi,
                    )
                    found_any = True
            except Exception:
                logger.debug("Chrome CDP strategy failed for %s", paper.doi, exc_info=True)

        if found_any:
            # Write a .done marker
            (dest / ".done").write_text(paper.doi)
            return dest

        # Clean up empty directory
        if dest.exists() and not any(f.is_file() and f.name != ".done" for f in dest.iterdir()):
            with contextlib.suppress(OSError):
                dest.rmdir()
        return None

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    # ── Strategy 1: Crossref API ──────────────────────────────────────

    async def _crossref_lookup(self, doi: str, dest: Path) -> int:
        """Query Crossref API for supplementary file links."""
        url = f"https://api.crossref.org/works/{doi}"
        try:
            resp = await self._client.get(url, timeout=httpx.Timeout(10.0))
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.debug("Crossref API HTTP %s for %s", exc.response.status_code, doi)
            return 0
        except httpx.RequestError as exc:
            logger.debug("Crossref API request error for %s: %s", doi, exc)
            return 0

        data = resp.json()
        message = data.get("message", {})

        count = 0
        # Look for links that are not "application/pdf" (i.e., supplementary)
        links = message.get("link", [])
        for link in links:
            ct = link.get("content-type", "")
            url = link.get("URL", "")
            if "pdf" not in ct.lower() and url:
                result = await self._fetch_one(url, dest)
                if result:
                    count += 1

        # Some DOIs have "supplementary-material" relation
        relations = message.get("relation", {})
        for rel_type, rel_list in relations.items():
            if "suppl" in rel_type.lower():
                for rel in rel_list:
                    id_val = rel.get("id", "")
                    if id_val:
                        result = await self._fetch_one(id_val, dest)
                        if result:
                            count += 1

        return count

    # ── Strategy 2: PubMed Central ────────────────────────────────────

    async def _pmc_lookup(self, doi: str, dest: Path) -> int:
        """Check PubMed Central for supplementary files."""
        # Resolve DOI → PMCID
        url = f"https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?ids={doi}&format=json"
        try:
            resp = await self._client.get(url, timeout=httpx.Timeout(10.0))
            resp.raise_for_status()
            data = resp.json()
            records = data.get("records", [])
            if not records:
                return 0
            pmcid = records[0].get("pmcid", "")
            if not pmcid:
                return 0
        except Exception:
            return 0

        count = 0
        # Fetch the PMC article page and look for supplementary links
        article_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/"
        try:
            resp = await self._client.get(article_url, timeout=httpx.Timeout(10.0))
            resp.raise_for_status()
        except Exception:
            return 0

        soup = BeautifulSoup(resp.text, "html.parser")
        # PMC supplementary links are usually in the "supplementary-material" area
        suppl_section = soup.find(id=re.compile(r"(supplementary|supplement)", re.IGNORECASE))
        if suppl_section:
            for a_tag in suppl_section.find_all("a", href=True):
                href = a_tag["href"]
                full_url = urljoin(article_url, href)
                if _SUPPL_RE.search(a_tag.get_text()) or _SUPPL_RE.search(href):
                    result = await self._fetch_one(full_url, dest)
                    if result:
                        count += 1

        # Also check PMC supplementary file naming convention:
        # https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmcid}/bin/{pmcid}-suppl-{name}.pdf
        pmc_id_num = pmcid.replace("PMC", "")
        suppl_base = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/bin"
        suppl_names = [
            f"{pmc_id_num}-suppl-{suffix}"
            for suffix in [
                "Supplement.pdf",
                "supplement.pdf",
                "Supplementary_data.pdf",
                "Supplementary_Data.xlsx",
                "suppl_data.zip",
                "supplementary_material.pdf",
                "Supplementary_Table.xlsx",
                "Supplementary_Table.pdf",
                "Supplementary_Figure.pdf",
                "Supplementary_Figure.tif",
                "Table_S1.xlsx",
                "Table_S2.xlsx",
                "Figure_S1.tif",
                "Figure_S2.tif",
            ]
        ]
        for name in suppl_names:
            file_url = f"{suppl_base}/{name}"
            result = await self._fetch_one(file_url, dest)
            if result:
                count += 1

        return count

    # ── Strategy 3: Publisher HTML page ───────────────────────────────

    async def _parse_publisher_page(self, doi: str, dest: Path) -> int:
        """Follow DOI URL and parse HTML for supplementary file links."""
        doi_url = f"https://doi.org/{doi}"
        try:
            resp = await self._client.get(doi_url, timeout=httpx.Timeout(15.0))
            resp.raise_for_status()
        except Exception:
            return 0

        if "text/html" not in resp.headers.get("content-type", ""):
            return 0

        soup = BeautifulSoup(resp.text, "html.parser")
        count = 0

        # Find supplementary sections by heading
        for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
            if _SECTION_RE.search(heading.get_text()):
                # Look for links in this section or the next sibling until next heading
                for sibling in heading.find_next_siblings():
                    if sibling.name and sibling.name.startswith("h"):
                        break
                    if sibling.name == "a" and sibling.get("href"):
                        href = sibling["href"]
                        full_url = urljoin(str(resp.url), href)
                        result = await self._fetch_one(full_url, dest)
                        if result:
                            count += 1
                    elif hasattr(sibling, "find_all"):
                        for a_tag in sibling.find_all("a", href=True):
                            full_url = urljoin(str(resp.url), a_tag["href"])
                            if _ANCHOR_RE.search(a_tag.get_text()) or _ANCHOR_RE.search(
                                a_tag.get("href", "")
                            ):
                                result = await self._fetch_one(full_url, dest)
                                if result:
                                    count += 1

        # Find all links with supplementary-related text/patterns
        for a_tag in soup.find_all("a", href=True):
            text = a_tag.get_text()
            href = a_tag["href"]
            if _ANCHOR_RE.search(text) or _ANCHOR_RE.search(href):
                full_url = urljoin(str(resp.url), href)
                # Avoid re-downloading already found files
                result = await self._fetch_one(full_url, dest)
                if result:
                    count += 1

        return count

    # ── Strategy 4: Known URL patterns ────────────────────────────────

    async def _common_patterns(self, doi: str, dest: Path) -> int:
        """Generate supplementary URLs from known publisher patterns."""
        doi_path = _doi_path(doi)
        doi_encoded = doi.replace("%", "%25").replace("/", "%2F")
        doi_path_flat = doi_path.replace("/", "_")

        count = 0
        for prefix, patterns in _PUBLISHER_SUPPL_PATTERNS.items():
            if doi.startswith(prefix):
                for pattern in patterns:
                    try:
                        url = pattern.format(
                            doi=doi,
                            doi_path=doi_path,
                            doi_encoded=doi_encoded,
                            doi_path_flat=doi_path_flat,
                            version=1,
                        )
                    except KeyError:
                        continue
                    result = await self._fetch_one(url, dest)
                    if result:
                        count += 1
                break  # only process first matching publisher

        return count

    # ── Helpers ───────────────────────────────────────────────────────

    async def _fetch_one(self, url: str, dest: Path) -> Path | None:
        """Download a single supplementary file and save to *dest*."""
        try:
            resp = await self._client.get(url, timeout=httpx.Timeout(30.0))
            resp.raise_for_status()
        except Exception:
            return None

        body = resp.content
        ct = resp.headers.get("content-type", "").lower()

        # Skip if too small
        if len(body) < 10:
            return None

        # ---- Content-type filtering ----------------------------------------
        # Reject HTML pages
        if "text/html" in ct:
            return None

        # Reject XML API responses (Elsevier full-text XML, PubMed XML, etc.)
        # These look like article metadata, not supplementary data files.
        if "xml" in ct:
            text = body[:1500].decode("utf-8", errors="replace")
            # API response markers — not actual data files.
            # We look for the root-element name because many XML data files
            # (SDF, MOL, SVG, etc.) also start with <?xml.
            # Strip XML declaration before checking root element
            check_text = text.lstrip()
            if check_text.startswith("<?xml"):
                m = _XML_DECL_RE.match(check_text)
                if m:
                    check_text = check_text[m.end() :].lstrip()
            if (
                check_text.startswith("<full-text-retrieval-response")
                or check_text.startswith("<soap:")
                or check_text.startswith("<error")
                or check_text.startswith("<serviceerror")
                or check_text.startswith("<atom:entry")
                or check_text.startswith("<rss")
            ):
                logger.debug("Skipped XML API response for %s", url)
                return None

        # Derive extension for final exclusion check
        ext = _get_ext(url, ct)

        # Reject if the derived extension is still HTML-adjacent or binary-generic
        if ext in (".html", ".htm", ".bin"):
            return None

        return _save_response(resp, dest)

    # ── Strategy 5: Chrome CDP ─────────────────────────────────────────

    async def _chrome_cdp_strategy(self, paper: Paper, dest: Path) -> int:
        # Launch Chrome via CDP, render the article page, extract supplementary links.
        # Bypasses Cloudflare/DataDome for publishers behind JS challenges.
        # Uses EZProxy if configured. Tries publisher-specific interaction first
        # (clicking buttons in supplementary sections), then falls back to
        # generic link extraction.
        if not HAS_PLAYWRIGHT:
            logger.debug("Chrome CDP: Playwright not installed")
            return 0

        chrome_path = resolve_browser_executable()
        if not chrome_path:
            logger.debug("Chrome CDP: Chrome not found")
            return 0

        doi_url = f"https://doi.org/{paper.doi}"
        target_url = self._proxify(doi_url)

        chrome_proc = None
        count = 0
        publisher = _detect_suppl_publisher(paper.doi) if paper.doi else None
        try:
            tmp_dir = str(default_profile_dir("supplementary"))
            Path(tmp_dir).mkdir(parents=True, exist_ok=True)
            cdp_port = _find_free_port()

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
                    *browser_launch_args(),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **spawn_process_kwargs(),
            )

            try:
                await _wait_for_cdp(cdp_port, 15)
            except TimeoutError:
                logger.debug("Chrome CDP: did not start in time")
                return 0

            cdp_url = f"http://127.0.0.1:{cdp_port}"
            async with async_playwright() as pw:
                browser = await pw.chromium.connect_over_cdp(cdp_url)
                context = browser.contexts[0] if browser.contexts else await browser.new_context()
                page = await context.new_page()

                # Navigate to article page
                logger.debug(
                    "Chrome CDP [%s]: navigating to %s",
                    publisher.name if publisher else "generic",
                    target_url[:100],
                )
                with contextlib.suppress(Exception):
                    await page.goto(target_url, wait_until="load", timeout=60000)
                await asyncio.sleep(3)

                # Wait for Cloudflare/JS challenges to resolve
                cf_keywords = (
                    "please wait",
                    "just a moment",
                    "security check",
                    "verify",
                    chr(35831) + chr(31509) + chr(20505),
                    chr(35831) + chr(31245) + chr(20505),
                )
                for _ in range(30):
                    title = await page.title()
                    if any(kw in title.lower() for kw in cf_keywords):
                        await asyncio.sleep(2)
                    else:
                        break

                logger.debug("Chrome CDP: page loaded, title=%r", await page.title())

                # Step 1: Try publisher-specific interaction
                if publisher:
                    try:
                        count = await self._suppl_publisher_interaction(
                            page, context, dest, publisher
                        )
                        if count > 0:
                            logger.info(
                                "Chrome CDP [%s]: publisher interaction found %d files",
                                publisher.name,
                                count,
                            )
                    except Exception:
                        logger.debug(
                            "Chrome CDP [%s]: publisher interaction error",
                            publisher.name,
                            exc_info=True,
                        )

                # Step 2: Generic link extraction (always runs, may find more)
                if count == 0:
                    links = await page.evaluate("""() => {
                        const results = [];
                        const visited = new Set();
                        const supplRe =
                            /supplement(?:ary|al)?|supporting|additional|extended|ESI|S\\d{1,2}/i;
                        const dataRe =
                            /\\.(zip|rar|tar|gz|csv|tsv|xlsx?|docx?|pptx?|tiff?|png|jpg|mov|mp4)$/i;

                        let sec = null;
                        for (const s of document.querySelectorAll('section, div, article')) {
                            if (
                                supplRe.test(s.textContent.slice(0, 200)) &&
                                /data|material|file|info/i.test(s.textContent.slice(0, 200))
                            ) {
                                sec = s; break;
                            }
                        }
                        if (!sec) {
                            for (const h of document.querySelectorAll('h1,h2,h3,h4,h5,h6')) {
                                if (supplRe.test(h.textContent)) {
                                    let el = h.nextElementSibling;
                                    while (el && !/^h[1-6]$/i.test(el.tagName)) {
                                        el = el.nextElementSibling;
                                    }
                                    sec = h.parentElement; break;
                                }
                            }
                        }

                        const anchors = sec
                            ? sec.querySelectorAll('a[href]')
                            : document.querySelectorAll('a[href]');
                        for (const a of anchors) {
                            const h = a.href;
                            const t = a.textContent.trim();
                            if (
                                !h ||
                                h.startsWith('javascript:') ||
                                h.startsWith('#') ||
                                visited.has(h)
                            ) continue;
                            visited.add(h);
                            if (sec) {
                                results.push({ text: t.slice(0, 80), href: h });
                            } else if (supplRe.test(t) || supplRe.test(h) || dataRe.test(h)) {
                                results.push({ text: t.slice(0, 80), href: h });
                            }
                        }
                        return results;
                    }""")

                    logger.debug(
                        "Chrome CDP: found %d supplementary links via generic extraction",
                        len(links),
                    )
                    for link in links:
                        saved = await self._playwright_download(page, dest, link["href"])
                        if saved:
                            count += 1

                await browser.close()

        except Exception:
            logger.debug("Chrome CDP strategy error", exc_info=True)
        finally:
            if chrome_proc:
                try:
                    kill_process_tree(chrome_proc)
                except Exception:
                    chrome_proc.kill()

        return count

    async def _suppl_publisher_interaction(self, page, context, dest, publisher) -> int:
        # Publisher-specific interaction to click buttons and find supplementary files.
        count = 0
        name = publisher.name
        logger.debug("Chrome CDP: running publisher interaction for %s", name)

        if name == "sciencedirect":
            # ScienceDirect: expand supplementary section, find mmc download links
            try:
                for btn_sel in [
                    "button[aria-label*='supplementary' i]",
                    "button[class*='supplementary']",
                    "#expand-supplementary",
                    "a[href*='mmc']",
                    "a[href*='#app']",
                ]:
                    btns = await page.query_selector_all(btn_sel)
                    for btn in btns:
                        try:
                            await btn.click()
                            await asyncio.sleep(1)
                        except Exception:
                            pass

                links = await page.evaluate("""() => {
                    const results = [];
                    const visited = new Set();
                    const supplArea = document.querySelector(
                        "section[class*='supplementary'], div[id*='supplementary'], "
                        "#supplementary-material, section[id$='-supplementary'], "
                        "div.app-extra");
                    if (!supplArea) return results;
                    for (const a of supplArea.querySelectorAll('a[href]')) {
                        const h = a.href;
                        if (!h || h.startsWith('#') || visited.has(h)) continue; visited.add(h);
                        results.push({ text: a.textContent.trim().slice(0,80), href: h });
                    }
                    return results;
                }""")
                for link in links:
                    saved = await self._playwright_download(page, dest, link["href"])
                    if saved:
                        count += 1
            except Exception:
                logger.debug("Chrome CDP [sciencedirect]: interaction error", exc_info=True)

        elif name == "nature":
            # Nature: find Supplementary Information button or section
            try:
                for sel in [
                    "a[data-track-action='supplementary info']",
                    "a.c-article__supplementary-data",
                    "a[href*='supplementary']",
                ]:
                    btn = await page.query_selector(sel)
                    if btn:
                        href = await btn.get_attribute("href")
                        if href:
                            saved = await self._playwright_download(page, dest, href)
                            if saved:
                                count += 1

                if count == 0:
                    sect = await page.query_selector(
                        "#Supplementary-Information-section, div[class*='supplementary']"
                    )
                    if sect:
                        links = await sect.evaluate("""(el) => {
                            const r = []; const v = new Set();
                            for (const a of el.querySelectorAll('a[href]')) {
                                const h = a.href;
                                if (!h || h.startsWith('#') || v.has(h)) continue; v.add(h);
                                r.push({ text: a.textContent.trim().slice(0,80), href: h });
                            } return r;
                        }""")
                        for link in links:
                            saved = await self._playwright_download(page, dest, link["href"])
                            if saved:
                                count += 1
            except Exception:
                logger.debug("Chrome CDP [nature]: interaction error", exc_info=True)

        elif name == "wiley":
            # Wiley: supporting information section + suppinfo URL
            try:
                for sel in [
                    "div[class*='supporting']",
                    "section[class*='supporting']",
                    "div.section[aria-labelledby*='supporting']",
                ]:
                    sect = await page.query_selector(sel)
                    if sect:
                        links = await sect.evaluate("""(el) => {
                            const r = []; const v = new Set();
                            for (const a of el.querySelectorAll('a[href]')) {
                                const h = a.href;
                                if (!h || h.startsWith('#') || v.has(h)) continue; v.add(h);
                                r.push({ text: a.textContent.trim().slice(0,80), href: h });
                            } return r;
                        }""")
                        for link in links:
                            saved = await self._playwright_download(page, dest, link["href"])
                            if saved:
                                count += 1
                        if count > 0:
                            break
            except Exception:
                logger.debug("Chrome CDP [wiley]: interaction error", exc_info=True)

        elif name == "mdpi":
            # MDPI: named sections #html-s1, #s1, etc.
            try:
                for s_num in range(1, 11):
                    for sel in [f"section#html-s{s_num}", f"section#s{s_num}"]:
                        sect = await page.query_selector(sel)
                        if sect:
                            links = await sect.evaluate("""(el) => {
                                const r = []; const v = new Set();
                                for (const a of el.querySelectorAll('a[href]')) {
                                    const h = a.href;
                                    if (!h || h.startsWith('#') || v.has(h)) continue; v.add(h);
                                    r.push({ text: a.textContent.trim().slice(0,80), href: h });
                                } return r;
                            }""")
                            for link in links:
                                saved = await self._playwright_download(page, dest, link["href"])
                                if saved:
                                    count += 1
                            break
            except Exception:
                logger.debug("Chrome CDP [mdpi]: interaction error", exc_info=True)

        elif name == "springer":
            # Springer: ESM section
            try:
                for sel in [
                    "div[class*='ESM']",
                    "section[class*='Supplementary']",
                    "div[class*='supplementary-material']",
                ]:
                    sect = await page.query_selector(sel)
                    if sect:
                        links = await sect.evaluate("""(el) => {
                            const r = []; const v = new Set();
                            for (const a of el.querySelectorAll('a[href]')) {
                                const h = a.href;
                                if (!h || h.startsWith('#') || v.has(h)) continue; v.add(h);
                                r.push({ text: a.textContent.trim().slice(0,80), href: h });
                            } return r;
                        }""")
                        for link in links:
                            saved = await self._playwright_download(page, dest, link["href"])
                            if saved:
                                count += 1
                        if count > 0:
                            break
            except Exception:
                logger.debug("Chrome CDP [springer]: interaction error", exc_info=True)

        elif name == "frontiers":
            # Frontiers: supplementary material section
            try:
                for sel in ["section[class*='Supplementary']", "div[class*='supplementary']"]:
                    sect = await page.query_selector(sel)
                    if sect:
                        links = await sect.evaluate("""(el) => {
                            const r = []; const v = new Set();
                            for (const a of el.querySelectorAll('a[href]')) {
                                const h = a.href;
                                if (!h || h.startsWith('#') || v.has(h)) continue; v.add(h);
                                r.push({ text: a.textContent.trim().slice(0,80), href: h });
                            } return r;
                        }""")
                        for link in links:
                            saved = await self._playwright_download(page, dest, link["href"])
                            if saved:
                                count += 1
                        if count > 0:
                            break
            except Exception:
                logger.debug("Chrome CDP [frontiers]: interaction error", exc_info=True)

        else:
            # Generic: try section selector for any configured publisher
            try:
                section_sel = _SUPPL_SECTION_SELECTORS.get(name, "")
                if section_sel:
                    sect = await page.query_selector(section_sel)
                    if sect:
                        links = await sect.evaluate("""(el) => {
                            const r = []; const v = new Set();
                            for (const a of el.querySelectorAll('a[href]')) {
                                const h = a.href;
                                if (!h || h.startsWith('#') || v.has(h)) continue; v.add(h);
                                r.push({ text: a.textContent.trim().slice(0,80), href: h });
                            } return r;
                        }""")
                        for link in links:
                            saved = await self._playwright_download(page, dest, link["href"])
                            if saved:
                                count += 1
            except Exception:
                pass

        return count

    async def _playwright_download(self, page, dest, url: str) -> bool:
        # Try direct HTTP download first (faster)
        saved = await self._fetch_one(url, dest)
        if saved:
            return True
        # Fallback: download through Playwright
        try:
            resp = await page.context.request.get(url)
            body = await resp.body()
            ct = resp.headers.get("content-type", "")
            if "text/html" not in ct and len(body) > 100:
                from httpx import Headers

                fake_resp = httpx.Response(
                    status_code=200,
                    headers=Headers({"content-type": ct or "application/octet-stream"}),
                    content=body,
                    request=httpx.Request("GET", url),
                )
                return _save_response(fake_resp, dest) is not None
        except Exception:
            pass
        return False

    def _proxify(self, url: str) -> str:
        # Wrap url through EZProxy if configured.
        if self._institutional_direct:
            return url
        if self._proxy_url:
            return self._proxy_url.rstrip("?=&") + url
        return url
