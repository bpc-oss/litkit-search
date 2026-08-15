"""Engine — deep search 主编排器.

流程:
  1. 主题扩展 (LLM / heuristic) → Strategy list
  2. 本体论扩展 (MeSH / PubChem / Wikipedia)
  3. 概念层次树构建
  4. 组合查询生成 → 30-50 个查询
  5. 多源并行检索 (litkit)
  6. 引文链追踪 (后向 + 前向)
  7. 珍珠增长 → 第二轮检索
  8. 最终去重 → 排序 → 输出
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from litkit.config import load_env
from litkit.core.cache import MetadataCache
from litkit.core.pipeline import Pipeline
from litkit.workflows.deep_search.citation_graph import chain_backward, chain_forward
from litkit.workflows.deep_search.ontology import expand_terms
from litkit.workflows.deep_search.pearl import grow as pearl_grow
from litkit.workflows.deep_search.pearl import grow_to_strategies as pearl_to_strategies
from litkit.workflows.deep_search.queries import (
    build_all_queries,
    build_hierarchy_queries,
    build_pearl_queries,
)
from litkit.workflows.deep_search.strategy import (
    build_hierarchy,
    expand_heuristic,
    expand_topic,
)
from litkit.workflows.deep_search.types import paper_to_record

logger = logging.getLogger(__name__)


async def run(
    topic: str,
    max_papers: int = 50,
    use_llm: bool = False,
    api_key: str | None = None,
    api_type: str = "anthropic",
    model: str = "",
    sources: list[str] | None = None,
    min_citations: int = 0,
    enable_citation_chain: bool = True,
    enable_pearl_growing: bool = True,
    enable_ontology: bool = False,
    verbose: bool = False,
) -> dict[str, Any]:
    """Deep search: topic sentence → expanded queries → multi-source → ranked results.

    Args:
        topic: Research topic sentence.
        max_papers: Max unique papers to return.
        use_llm: Use LLM for topic expansion.
        api_key: LLM API key.
        api_type: "anthropic" or "openai".
        model: Override LLM model name.
        sources: Override search sources.
        min_citations: Minimum citation filter.
        enable_citation_chain: Enable backward/forward citation chaining.
        enable_pearl_growing: Enable pearl growing (2nd round).
        enable_ontology: Enable ontology expansion (MeSH/PubChem/Wikipedia).
        verbose: Enable detailed logging.

    Returns:
        dict with full search results and metadata.
    """
    if verbose:
        logging.getLogger("litkit.workflows.deep_search").setLevel(logging.INFO)

    start = time.monotonic()
    logger.info("Deep search: %s", topic)

    # Load .env so DEEPSEEK_API_KEY etc are available to all phases
    _ = load_env()

    # -----------------------------------------------------------------------
    # Phase 1: Topic expansion → strategies
    # -----------------------------------------------------------------------
    t0 = time.monotonic()
    if use_llm:
        strategies = expand_topic(topic, api_key, api_type, model)
    else:
        strategies = expand_heuristic(topic)
    logger.info(
        "Phase 1 (strategies): %d strategies in %.1fs",
        len(strategies), time.monotonic() - t0,
    )

    # -----------------------------------------------------------------------
    # Phase 2: Hierarchy — build concept tree (LLM)
    # -----------------------------------------------------------------------
    hierarchy_queries: list[str] = []
    if use_llm:
        t0 = time.monotonic()
        hierarchy = build_hierarchy(topic, api_key, api_type)
        if hierarchy:
            hierarchy_queries = build_hierarchy_queries(hierarchy)
        logger.info(
            "Phase 2 (hierarchy): %d hierarchy queries in %.1fs",
            len(hierarchy_queries), time.monotonic() - t0,
        )

    # -----------------------------------------------------------------------
    # Phase 3: Ontology expansion
    # -----------------------------------------------------------------------
    ontology_terms: dict[str, list[str]] = {}
    if enable_ontology:
        t0 = time.monotonic()
        cache = MetadataCache()
        # Collect key terms from strategies
        all_terms: list[str] = []
        for s in strategies:
            for g in s.synonym_groups:
                for t in g.terms[:3]:
                    if t not in all_terms:
                        all_terms.append(t)
        ontology_terms = await expand_terms(all_terms[:5], cache)
        logger.info(
            "Phase 3 (ontology): %d terms expanded in %.1fs",
            len(ontology_terms), time.monotonic() - t0,
        )

    # -----------------------------------------------------------------------
    # Phase 4: Build all queries (combinatorial explosion)
    # -----------------------------------------------------------------------
    t0 = time.monotonic()
    strategy_queries = build_all_queries(strategies)
    all_queries = strategy_queries + hierarchy_queries

    # Add ontology-derived queries
    for _, expanded in ontology_terms.items():
        for e in expanded[:5]:
            if e not in all_queries:
                all_queries.append(e)

    logger.info(
        "Phase 4 (queries): %d total queries in %.1fs",
        len(all_queries), time.monotonic() - t0,
    )

    # -----------------------------------------------------------------------
    # Phase 5: Multi-source parallel search
    # -----------------------------------------------------------------------
    t0 = time.monotonic()
    config = load_env()
    cache = MetadataCache()
    pipeline = Pipeline(config, cache)
    per_query = max(5, max_papers // max(len(all_queries), 1))
    src_list = sources or ["crossref", "pubmed", "openalex"]

    tasks = [_search_one(pipeline, q, src_list, per_query) for q in all_queries]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    raw_papers: list[dict[str, Any]] = []
    for r in results:
        if isinstance(r, list):
            raw_papers.extend(r)
    logger.info("Phase 5 (search): %d raw results in %.1fs", len(raw_papers), time.monotonic() - t0)

    # -----------------------------------------------------------------------
    # Phase 6: Citation chaining
    # -----------------------------------------------------------------------
    chain_papers: list[dict[str, Any]] = []
    if enable_citation_chain and len(raw_papers) > 0:
        t0 = time.monotonic()
        # Take top papers for citation chaining
        deduped = _deduplicate(raw_papers)
        sorted_papers = sorted(deduped, key=lambda x: -x.get("citation_count", 0))

        backward = await chain_backward(sorted_papers[:10])
        forward = await chain_forward(sorted_papers[:5])

        chain_papers = backward + forward
        logger.info(
            "Phase 6 (citation chain): %d backward + %d forward in %.1fs",
            len(backward), len(forward), time.monotonic() - t0,
        )

    # -----------------------------------------------------------------------
    # Phase 7: Pearl growing → 2nd round
    # -----------------------------------------------------------------------
    pearl_papers: list[dict[str, Any]] = []
    if enable_pearl_growing and len(raw_papers) > 0:
        t0 = time.monotonic()
        # Collect papers for pearl growing
        candidate_papers = raw_papers + chain_papers

        keywords = pearl_grow(candidate_papers, top_n=15)
        if keywords:
            _ = pearl_to_strategies(keywords, topic)
            pearl_queries = build_pearl_queries(keywords)

            pearl_tasks = [
                _search_one(pipeline, q, src_list, per_query)
                for q in pearl_queries[:15]
            ]
            pearl_results = await asyncio.gather(*pearl_tasks, return_exceptions=True)
            for r in pearl_results:
                if isinstance(r, list):
                    for p in r:
                        p["from_pearl_growing"] = True
                    pearl_papers.extend(r)

        logger.info(
            "Phase 7 (pearl growing): %d keywords, %d more papers in %.1fs",
            len(keywords), len(pearl_papers), time.monotonic() - t0,
        )

    # -----------------------------------------------------------------------
    # Phase 8: Final dedup + sort
    # -----------------------------------------------------------------------
    all_found = raw_papers + chain_papers + pearl_papers
    deduped = _deduplicate(all_found)

    # Sort: DOI-first, citation count desc
    deduped.sort(key=lambda p: (
        1 if p.get("doi") else 0,
        p.get("citation_count", 0),
    ), reverse=True)

    # Filter by min citations
    if min_citations > 0:
        deduped = [p for p in deduped if (p.get("citation_count") or 0) >= min_citations]

    # Trim
    final_papers = deduped[:max_papers]

    # Format output
    result_papers = []
    for p in final_papers:
        result_papers.append({
            "doi": p.get("doi", ""),
            "title": p.get("title", "")[:200],
            "year": p.get("year", 0),
            "journal": p.get("journal", ""),
            "source": p.get("source", ""),
            "citation_count": p.get("citation_count", 0),
            "authors": list(p.get("authors", []))[:5],
            "abstract": (p.get("abstract") or "")[:500],
            "keywords": list(p.get("keywords", []))[:10],
            "from_citation_chain": p.get("from_citation_chain", False),
            "from_pearl_growing": p.get("from_pearl_growing", False),
            "chain_direction": p.get("chain_direction", ""),
        })

    years = [p["year"] for p in result_papers if p["year"]]
    elapsed = time.monotonic() - start

    return {
        "topic": topic,
        "strategy_count": len(strategies),
        "total_queries": len(all_queries),
        "total_raw": len(all_found),
        "unique_papers": len(result_papers),
        "papers": result_papers,
        "year_range": [min(years), max(years)] if years else [0, 0],
        "citation_chain_count": len(chain_papers),
        "pearl_growing_count": len(pearl_papers),
        "elapsed_seconds": round(elapsed, 1),
    }


async def _search_one(
    pipeline: Pipeline,
    query: str,
    sources: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    """Search one query via litkit pipeline."""
    try:
        raw = await pipeline.search(query, sources=sources, limit=limit)
        return [paper_to_record(p) for p in raw]
    except Exception as e:
        logger.debug("Search failed for %r: %s", query, e)
        return []


def _deduplicate(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate by DOI or title."""
    seen: dict[str, dict[str, Any]] = {}
    for p in papers:
        key = (p.get("doi") or "").lower().strip()
        if not key:
            # Use first 50 chars of title as fallback key
            title = (p.get("title") or "").strip()[:50].lower()
            key = title if title else id(p)

        existing = seen.get(key)
        if existing is None:
            seen[key] = p
        else:
            # Keep the one with more complete data
            has_better_abstract = p.get("abstract") and not existing.get("abstract")
            more_cited = p.get("citation_count", 0) > existing.get("citation_count", 0)
            if has_better_abstract or more_cited:
                seen[key] = p
    return list(seen.values())
