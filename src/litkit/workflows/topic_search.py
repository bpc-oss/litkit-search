"""Workflow: topic-search — 一句话主题 → LLM扩展 → 多源并行检索 → 去重排序.

复制自 review-agent 的 SearchStrategyAgent + LiteratureRetriever 能力：
给定一句话研究主题，自动扩展为多组搜索策略（同义词组、纳入排除标准），
通过 litkit 多源并行检索，DOI 去重后按引用数排序。

Usage:
    import asyncio
    from litkit.workflows.topic_search import run

    result = asyncio.run(run("inulin fermentation by Bifidobacterium SCFA"))
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any

from litkit.config import load_env
from litkit.core.cache import MetadataCache
from litkit.core.pipeline import Pipeline

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM prompt — 一句话主题 → 结构化搜索策略
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an expert in systematic literature search for microbiome and fermentation science.

Your task:
Given a research topic sentence, design a comprehensive literature search strategy
suitable for databases like PubMed, Scopus, Crossref, and OpenAlex.

Return ONLY valid JSON. No markdown, no explanations.

Required JSON format:
{
  "strategies": [
    {
      "core_query": "the main search query string",
      "rationale": "why this query captures the topic",
      "synonym_groups": [
        {
          "concept": "concept name",
          "terms": ["term1", "term2", "term3"]
        }
      ],
      "inclusion_criteria": ["criterion 1"],
      "exclusion_criteria": ["criterion 1"],
      "suggested_databases": ["crossref", "pubmed", "openalex"]
    }
  ]
}

Guidelines:
- Generate 3-5 strategies covering different angles of the topic
- Each strategy should have 2-4 synonym groups with 2-5 terms each
- Terms should include common synonyms, broader/narrower terms, and spelling variants
- For microbiome topics, include terms like: bacterial taxa names, SCFA names,
  polysaccharide names, fermentation method terms, experimental model terms
- Inclusion/exclusion criteria should be specific enough to filter relevant papers
"""


# ---------------------------------------------------------------------------
# Query expansion
# ---------------------------------------------------------------------------


def expand_heuristic(topic: str) -> list[dict[str, Any]]:
    """Keyword-based expansion without external LLM API.

    Extracts key terms from the topic sentence and builds query variants.
    Useful as fallback or when no API key is configured.
    """
    terms = _extract_key_terms(topic)
    return [
        {
            "core_query": topic,
            "synonym_groups": [{"concept": "primary", "terms": terms[:5]}],
            "databases": ["crossref", "pubmed", "openalex"],
        },
        {
            "core_query": " ".join(terms[:3]),
            "synonym_groups": [{"concept": "expanded", "terms": terms[3:8]}],
            "databases": ["crossref", "pubmed"],
        },
    ]


def expand_with_llm(
    topic: str,
    api_key: str | None = None,
    api_type: str = "anthropic",
    model: str = "",
) -> list[dict[str, Any]]:
    """Expand a topic sentence using an LLM API.

    Falls back to heuristic expansion on failure.
    """
    if api_type == "anthropic":
        return _call_anthropic(topic, api_key, model)
    elif api_type == "openai":
        return _call_openai(topic, api_key, model)
    else:
        logger.warning("Unknown api_type=%s, falling back to heuristic", api_type)
        return expand_heuristic(topic)


def _extract_key_terms(topic: str) -> list[str]:
    """Extract meaningful terms from a topic sentence."""
    stopwords = {
        "the",
        "a",
        "an",
        "of",
        "in",
        "by",
        "to",
        "for",
        "and",
        "or",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "has",
        "have",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "shall",
        "can",
        "need",
        "dares",
        "ought",
        "used",
        "its",
        "it",
        "this",
        "that",
        "these",
        "those",
        "we",
        "they",
        "their",
        "our",
        "my",
        "your",
        "his",
        "her",
        "from",
        "with",
        "on",
        "at",
        "as",
        "but",
        "not",
        "no",
        "nor",
        "both",
        "each",
        "every",
        "all",
        "any",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "only",
        "own",
        "same",
        "so",
        "than",
        "too",
        "very",
        "just",
        "about",
        "above",
        "after",
        "again",
        "against",
        "because",
        "before",
        "between",
        "down",
        "during",
        "out",
        "over",
        "through",
        "under",
        "up",
        "while",
        "into",
        "upon",
    }
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9\-]+", topic.lower())
    return [w for w in words if w not in stopwords and len(w) > 2]


def _parse_llm_response(raw: str) -> list[dict[str, Any]]:
    """Parse JSON from LLM response into strategy dicts."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    data = json.loads(cleaned)
    strategies_data = data.get("strategies", [data])
    return [
        {
            "core_query": sd.get("core_query", ""),
            "synonym_groups": sd.get("synonym_groups", []),
            "inclusion_criteria": sd.get("inclusion_criteria", []),
            "exclusion_criteria": sd.get("exclusion_criteria", []),
            "databases": sd.get("suggested_databases", ["crossref", "pubmed", "openalex"]),
        }
        for sd in strategies_data
    ]


def _call_anthropic(
    topic: str, api_key: str | None = None, model: str = ""
) -> list[dict[str, Any]]:
    """Call Anthropic API for topic expansion."""
    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        logger.warning("No Anthropic API key, using heuristic")
        return expand_heuristic(topic)

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=key)
        model_name = model or "claude-sonnet-4-20250514"
        response = client.messages.create(
            model=model_name,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Topic: {topic}"}],
        )
        raw = ""
        for block in response.content:
            if block.type == "text":
                raw = str(getattr(block, "text", ""))
                break
        return _parse_llm_response(raw) if raw else expand_heuristic(topic)
    except Exception as e:
        logger.warning("Anthropic API call failed: %s, using heuristic", e)
        return expand_heuristic(topic)


def _call_openai(topic: str, api_key: str | None = None, model: str = "") -> list[dict[str, Any]]:
    """Call OpenAI-compatible API for topic expansion."""
    key = api_key or os.environ.get("OPENAI_API_KEY", "")
    if not key:
        logger.warning("No OpenAI API key, using heuristic")
        return expand_heuristic(topic)

    try:
        from openai import OpenAI

        client = OpenAI(api_key=key)
        model_name = model or "gpt-4o"
        response = client.chat.completions.create(
            model=model_name,
            max_tokens=2048,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Topic: {topic}"},
            ],
        )
        raw = response.choices[0].message.content or ""
        return _parse_llm_response(raw) if raw else expand_heuristic(topic)
    except Exception as e:
        logger.warning("OpenAI API call failed: %s, using heuristic", e)
        return expand_heuristic(topic)


# ---------------------------------------------------------------------------
# Strategy → query variants
# ---------------------------------------------------------------------------


def _build_variants(strategy: dict[str, Any]) -> list[str]:
    """Generate multiple query strings from a strategy's synonym groups."""
    core = strategy["core_query"]
    groups = strategy.get("synonym_groups", [])
    if not groups:
        return [core]
    variants = [core]
    for sg in groups:
        for term in sg.get("terms", [])[:3]:
            variants.append(f"{core} {term}")
    return variants


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def run(
    topic: str,
    max_papers: int = 30,
    use_llm: bool = False,
    api_key: str | None = None,
    api_type: str = "anthropic",
    model: str = "",
    sources: list[str] | None = None,
    min_citations: int = 0,
) -> dict[str, Any]:
    """Search literature by topic sentence.

    Args:
        topic: A one-sentence description of the research topic.
        max_papers: Maximum number of unique papers to return.
        use_llm: Whether to use LLM-based query expansion.
        api_key: API key for LLM (if use_llm=True).
        api_type: "anthropic" or "openai".
        model: Override LLM model name.
        sources: Override search sources (default crossref/pubmed/openalex).
        min_citations: Minimum citation count filter.

    Returns:
        dict with keys: topic, strategies, queries, total_raw, unique_papers, papers[]
    """
    logger.info("Topic search: %s", topic)

    # Step 1: Expand topic into search strategies
    if use_llm:
        strategies = expand_with_llm(topic, api_key=api_key, api_type=api_type, model=model)
    else:
        strategies = expand_heuristic(topic)

    # Step 2: Build query variants
    all_queries: list[str] = []
    sources_set: set[str] = set()
    for s in strategies:
        all_queries.extend(_build_variants(s))
        sources_set.update(s.get("databases", ["crossref", "pubmed", "openalex"]))

    if not sources_set:
        sources_set = {"crossref", "pubmed", "openalex"}

    # Step 3: Search via litkit
    config = load_env()
    cache = MetadataCache()
    pipeline = Pipeline(config, cache)
    per_query = max(5, max_papers // max(len(all_queries), 1))
    src_list = sources or list(sources_set)

    tasks = [_search_one(pipeline, q, src_list, per_query) for q in all_queries]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    raw_papers: list[dict[str, Any]] = []
    for r in results:
        if isinstance(r, list):
            raw_papers.extend(r)

    # Step 4: Deduplicate by DOI
    seen: dict[str, dict[str, Any]] = {}
    for p in raw_papers:
        key = p.get("doi") or p.get("title", "")
        if not key:
            continue
        if key not in seen or p.get("citation_count", 0) > seen[key].get("citation_count", 0):
            seen[key] = p

    papers = sorted(seen.values(), key=lambda x: -x.get("citation_count", 0))

    # Step 5: Filter by min citations
    if min_citations > 0:
        papers = [p for p in papers if (p.get("citation_count") or 0) >= min_citations]

    # Step 6: Trim
    papers = papers[:max_papers]

    # Step 7: Format output
    result_papers = []
    for p in papers:
        result_papers.append(
            {
                "doi": p.get("doi", ""),
                "title": p.get("title", ""),
                "year": p.get("year", 0),
                "journal": p.get("journal", ""),
                "source": p.get("source", ""),
                "citation_count": p.get("citation_count", 0),
                "authors": p.get("authors", []),
                "abstract": (p.get("abstract") or "")[:300],
            }
        )

    years = [p["year"] for p in result_papers if p["year"]]

    return {
        "topic": topic,
        "strategy_count": len(strategies),
        "queries_used": all_queries,
        "total_raw": len(raw_papers),
        "unique_papers": len(result_papers),
        "year_range": [min(years), max(years)] if years else [0, 0],
        "papers": result_papers,
    }


async def _search_one(
    pipeline: Pipeline,
    query: str,
    sources: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    """Search one query via litkit."""
    papers: list[dict[str, Any]] = []
    try:
        raw = await pipeline.search(query, sources=sources, limit=limit)
        for p in raw:
            papers.append(
                {
                    "doi": getattr(p, "doi", None) or "",
                    "title": getattr(p, "title", "") or "",
                    "year": getattr(p, "year", 0) or 0,
                    "journal": getattr(p, "journal", "") or "",
                    "source": getattr(p, "source", "") or "",
                    "citation_count": getattr(p, "citations_count", 0) or 0,
                    "authors": [a.full or a.family for a in getattr(p, "authors", []) if a][:5],
                    "abstract": getattr(p, "abstract", "") or "",
                }
            )
    except Exception as e:
        logger.debug("Search failed for %r: %s", query, e)
    return papers
