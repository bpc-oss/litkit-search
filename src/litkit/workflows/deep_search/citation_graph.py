"""Citation chainer — 后向 + 前向引用追踪.

通过 OpenAlex API 递归获取：
  - 后向引用 (参考文献)
  - 前向引用 (施引文献)

识别种子论文的最相关/高引邻居。
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

OPENALEX_BASE = "https://api.openalex.org/works"
MAX_PAPERS = 20  # 每个方向最多返回
_OPENALEX_SELECT = "id,doi,title,publication_year,cited_by_count,authorships,open_access,keywords"
_OPENALEX_SELECT_WITH_REFS = f"{_OPENALEX_SELECT},referenced_works"


async def chain_backward(
    papers: list[dict[str, Any]],
    max_depth: int = 1,
    max_papers: int = MAX_PAPERS,
) -> list[dict[str, Any]]:
    """Fetch references (backward citations) for a list of papers.

    For each paper with a DOI, fetches its references via OpenAlex.
    """
    if max_depth <= 0:
        return []

    dois = [p.get("doi", "") for p in papers if p.get("doi")]
    if not dois:
        logger.info("chain_backward: no DOIs found in seed papers")
        return []

    # resolve DOIs to OpenAlex work IDs and fetch references
    results: list[dict[str, Any]] = []
    seen_dois: set[str] = _collect_dois(papers)

    logger.info("chain_backward: %d seed DOIs", len(dois))

    for doi in dois[:8]:
        refs = await _fetch_references(doi)
        for ref in refs:
            d = ref.get("doi", "")
            if d and d.lower() not in seen_dois:
                seen_dois.add(d.lower())
                ref["from_citation_chain"] = True
                ref["chain_direction"] = "backward"
                results.append(ref)
                if len(results) >= max_papers:
                    break
        if len(results) >= max_papers:
            break

    logger.info("chain_backward: %d new papers", len(results))
    return results


async def chain_forward(
    papers: list[dict[str, Any]],
    max_depth: int = 1,
    max_papers: int = MAX_PAPERS,
) -> list[dict[str, Any]]:
    """Fetch citing papers for a list of papers via OpenAlex."""
    if max_depth <= 0:
        return []

    dois = [p.get("doi", "") for p in papers if p.get("doi")]
    if not dois:
        return []

    results: list[dict[str, Any]] = []
    seen_dois: set[str] = _collect_dois(papers)

    logger.info("chain_forward: %d seed DOIs", len(dois))

    for doi in dois[:5]:
        # Step 1: resolve DOI to OpenAlex work ID
        oa_id = await _resolve_to_openalex_id(doi)
        if not oa_id:
            continue

        # Step 2: use that ID for cites filter
        citing = await _fetch_citing_by_id(oa_id)
        for c in citing:
            d = c.get("doi", "")
            if d and d.lower() not in seen_dois:
                seen_dois.add(d.lower())
                c["from_citation_chain"] = True
                c["chain_direction"] = "forward"
                results.append(c)
                if len(results) >= max_papers:
                    break
        if len(results) >= max_papers:
            break

    logger.info("chain_forward: %d new papers", len(results))
    return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _collect_dois(papers: list[dict[str, Any]]) -> set[str]:
    """Collect existing DOIs from papers to avoid duplicates."""
    seen: set[str] = set()
    for p in papers:
        d = p.get("doi", "")
        if d:
            seen.add(d.lower().strip())
    return seen


async def _resolve_to_openalex_id(doi: str) -> str | None:
    """Resolve a DOI to an OpenAlex work ID (e.g. W12345678)."""
    doi_clean = doi.lower().strip()
    doi_clean = doi_clean.replace("https://doi.org/", "").replace("http://dx.doi.org/", "")

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(
                f"{OPENALEX_BASE}/doi:{doi_clean}",
                params={"select": "id"},
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            raw = data.get("id", "")
            if raw.startswith("https://openalex.org/"):
                return raw.replace("https://openalex.org/", "")
            return raw
        except (httpx.HTTPError, ValueError):
            return None


async def _fetch_references(doi: str) -> list[dict[str, Any]]:
    """Fetch all references of a paper (recursive batch)."""
    doi_clean = doi.lower().strip()
    doi_clean = doi_clean.replace("https://doi.org/", "").replace("http://dx.doi.org/", "")

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            # Get the work record including referenced_works
            resp = await client.get(
                f"{OPENALEX_BASE}/doi:{doi_clean}",
                params={"select": _OPENALEX_SELECT_WITH_REFS},
            )
            if resp.status_code != 200:
                return []

            data = resp.json()
            ref_ids = data.get("referenced_works", [])
            if not ref_ids:
                return []

            # Convert URLs to bare IDs
            bare_ids = []
            for wid in ref_ids[:50]:
                wid = wid.strip()
                if wid.startswith("https://openalex.org/"):
                    bare_ids.append(wid.replace("https://openalex.org/", ""))
                else:
                    bare_ids.append(wid)

            # Fetch in batches
            all_refs: list[dict[str, Any]] = []
            for i in range(0, len(bare_ids), 25):
                batch = bare_ids[i : i + 25]
                batch_refs = await _fetch_works_batch(batch)
                all_refs.extend(batch_refs)

            return all_refs

        except (httpx.HTTPError, ValueError) as e:
            logger.debug("OpenAlex references failed for %s: %s", doi, e)
            return []


async def _fetch_citing_by_id(oa_id: str) -> list[dict[str, Any]]:
    """Fetch papers that cite a given OpenAlex work ID."""
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(
                f"{OPENALEX_BASE}",
                params={
                    "filter": f"cites:{oa_id}",
                    "sort": "cited_by_count:desc",
                    "per_page": 25,
                    "select": _OPENALEX_SELECT,
                },
            )
            if resp.status_code != 200:
                return []

            data = resp.json()
            return _parse_openalex_results(data.get("results", []))

        except (httpx.HTTPError, ValueError) as e:
            logger.debug("OpenAlex citing failed for %s: %s", oa_id, e)
            return []


async def _fetch_works_batch(work_ids: list[str]) -> list[dict[str, Any]]:
    """Fetch multiple OpenAlex works by their ID."""
    if not work_ids:
        return []

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            filter_val = "|".join(work_ids)
            resp = await client.get(
                f"{OPENALEX_BASE}",
                params={
                    "filter": f"openalex_id:{filter_val}",
                    "select": _OPENALEX_SELECT,
                    "per_page": len(work_ids),
                },
            )
            if resp.status_code != 200:
                logger.debug("batch fetch status %d", resp.status_code)
                return []
            data = resp.json()
            results = data.get("results", [])
            logger.debug("batch fetch %d ids → %d results", len(work_ids), len(results))
            return _parse_openalex_results(results)
        except (httpx.HTTPError, ValueError) as e:
            logger.debug("batch fetch failed: %s", e)
            return []


def _parse_openalex_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse OpenAlex API results into paper dicts."""
    papers: list[dict[str, Any]] = []
    for work in results:
        doi = (work.get("doi") or "").replace("https://doi.org/", "")
        papers.append(
            {
                "doi": doi,
                "title": work.get("title", "") or "",
                "year": work.get("publication_year", 0) or 0,
                "journal": "",
                "source": "openalex",
                "citation_count": work.get("cited_by_count", 0) or 0,
                "authors": tuple(
                    a.get("author", {}).get("display_name", "")
                    for a in work.get("authorships", [])[:8]
                    if a.get("author")
                ),
                "abstract": "",
                "keywords": tuple(
                    kw.get("display_name", "")
                    for kw in work.get("keywords", [])[:10]
                    if kw.get("display_name")
                ),
                "is_open_access": bool(work.get("open_access", {}).get("is_oa", False)),
                "from_citation_chain": True,
            }
        )
    return papers
