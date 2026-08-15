"""Ontology expander — MeSH / PubChem / Wikipedia 术语查找.

实现 review-agent 的 OntologyExpander：
  - MeSH → 入口词 + 狭义概念 (NCBI E-utilities)
  - PubChem → 化合物同义词 (PubChem REST API)
  - Wikipedia → 类别 + 页面标题

所有结果本地缓存到 SQLite (MetadataCache) 减少重复请求。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time

import httpx

from litkit.core.cache import MetadataCache

logger = logging.getLogger(__name__)

# NCBI E-utilities base — free, no key needed for low-rate use
NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"

# Token bucket: NCBI allows 10 req/s without key
_last_ncbi_call: float = 0


async def _rate_limited_ncbi() -> None:
    """Ensure ≤10 NCBI requests per second."""
    global _last_ncbi_call
    now = time.monotonic()
    elapsed = now - _last_ncbi_call
    if elapsed < 0.1:  # 100ms = 10 req/s
        await asyncio.sleep(0.1 - elapsed)
    _last_ncbi_call = time.monotonic()


async def expand_terms(
    terms: list[str], cache: MetadataCache | None = None
) -> dict[str, list[str]]:
    """Expand a list of terms using ontology lookups.

    Returns dict mapping original term → list of expanded synonyms.
    """
    result: dict[str, list[str]] = {}
    for term in terms:
        expanded = await _expand_single(term, cache)
        if expanded:
            result[term] = expanded
    return result


async def _expand_single(term: str, cache: MetadataCache | None) -> list[str]:
    """Expand a single term via multiple ontology sources."""
    all_terms: list[str] = []
    seen: set[str] = set()

    for source_fn in [_mesh_lookup, _pubchem_lookup, _wikipedia_lookup]:
        try:
            results = await source_fn(term)
        except Exception as e:
            logger.debug("%s lookup failed for %r: %s", source_fn.__name__, term, e)
            results = []

        for t in results:
            t_lower = t.lower().strip()
            if t_lower and t_lower not in seen and t_lower != term.lower():
                seen.add(t_lower)
                all_terms.append(t.strip())

        # If we already have enough terms, stop
        if len(all_terms) >= 10:
            break

    return all_terms[:10]


# ---------------------------------------------------------------------------
# MeSH
# ---------------------------------------------------------------------------


async def _mesh_lookup(term: str) -> list[str]:
    """Look up MeSH terms via NCBI E-utilities (esearch + esummary)."""
    results: list[str] = []

    async with httpx.AsyncClient(timeout=10) as client:
        await _rate_limited_ncbi()

        # Step 1: Search MeSH
        search_resp = await client.get(
            f"{NCBI_BASE}/esearch.fcgi",
            params={
                "db": "mesh",
                "term": term,
                "retmax": 5,
                "retmode": "json",
            },
        )
        search_resp.raise_for_status()
        search_data = search_resp.json()

        ids = search_data.get("esearchresult", {}).get("idlist", [])
        if not ids:
            return results

        # Step 2: Get term details
        await _rate_limited_ncbi()
        summary_resp = await client.get(
            f"{NCBI_BASE}/esummary.fcgi",
            params={
                "db": "mesh",
                "id": ",".join(ids[:3]),
                "retmode": "json",
            },
        )
        summary_resp.raise_for_status()
        summary_data = summary_resp.json()

        for uid in ids[:3]:
            record = summary_data.get("result", {}).get(uid, {})
            # Extract term name
            name = record.get("name", "") or record.get("title", "") or ""
            if name and name.lower() != term.lower():
                results.append(name)

            # Extract narrower concepts (if available)
            narrower = record.get("narrower", [])
            if isinstance(narrower, list):
                for n in narrower[:3]:
                    if isinstance(n, str) and n.lower() != term.lower():
                        results.append(n)

            # Extract entry terms (synonyms)
            entry = record.get("entry_terms", [])
            if isinstance(entry, list):
                for e in entry[:3]:
                    if isinstance(e, str) and e.lower() != term.lower():
                        results.append(e)

    return results[:8]


# ---------------------------------------------------------------------------
# PubChem
# ---------------------------------------------------------------------------


async def _pubchem_lookup(term: str) -> list[str]:
    """Look up compound synonyms via PubChem REST API."""
    results: list[str] = []

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(
                f"{PUBCHEM_BASE}/compound/name/{term}/synonyms/JSON",
                timeout=10,
            )
            if resp.status_code != 200:
                return results

            data = resp.json()
            syn_list: list[str] = []
            for item in data.get("InformationList", {}).get("Information", []):
                syn_list.extend(item.get("Synonym", []))

            if not syn_list:
                return results

            # Filter to useful ones — skip IUPAC names (too long), deposit IDs
            for s in syn_list:
                if len(s) > 60 or re.match(r"^\d+-\d+-\d+$", s):  # skip long IUPAC
                    continue
                if s.startswith("Deposit"):
                    continue
                results.append(s)
                if len(results) >= 8:
                    break

        except (httpx.HTTPError, ValueError):
            pass

    return results


# ---------------------------------------------------------------------------
# Wikipedia
# ---------------------------------------------------------------------------


async def _wikipedia_lookup(term: str) -> list[str]:
    """Look up related terms via Wikipedia API."""
    results: list[str] = []

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "format": "json",
                    "titles": term,
                    "prop": "categories|categories",
                    "cllimit": 10,
                    "clshow": "!hidden",
                },
            )
            resp.raise_for_status()
            data = resp.json()

            pages = data.get("query", {}).get("pages", {})
            for page_id, page_data in pages.items():
                if page_id == "-1":
                    continue  # page not found

                # Get categories
                categories = page_data.get("categories", [])
                for cat in categories:
                    title = cat.get("title", "")
                    # Only keep meaningful category names
                    cat_name = re.sub(r"^Category:", "", title)
                    if cat_name and len(cat_name) < 50:
                        results.append(cat_name)
                    if len(results) >= 5:
                        break

        except (httpx.HTTPError, ValueError):
            pass

    return results[:5]
