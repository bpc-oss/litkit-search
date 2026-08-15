"""Topic strategy generation — 一句话主题 → 多层次搜索策略.

包含：
  - LLM-based 策略生成 (Anthropic / OpenAI)
  - Heuristic 关键词提取 (fallback)
  - 主题层次树 (父概念 / 兄弟 / 变体 / 机制锚点)
  - 扩展/收缩策略生成
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from litkit.workflows.deep_search.types import Strategy, SynonymGroup

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 主系统提示 — 生成搜索策略
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an expert systematic-review search strategist.

Given a research topic sentence, produce a comprehensive search strategy
suitable for databases like PubMed, Scopus, Web of Science, Crossref, and OpenAlex.

Return ONLY valid JSON. No markdown, no commentary.

Required JSON format:
{
  "strategies": [
    {
      "core_query": "the main search query as a short phrase",
      "rationale": "one-sentence explanation",
      "query_type": "general|broad|narrow|mechanism|system",
      "synonym_groups": [
        {
          "concept": "Concept A",
          "terms": ["term1", "term2", "term3", ...]
        }
      ],
      "inclusion_criteria": ["criterion"],
      "exclusion_criteria": ["criterion"],
      "suggested_databases": ["crossref", "pubmed", "openalex"]
    }
  ]
}

Guidelines:
- Generate 4-7 strategies covering DIFFERENT angles of the topic
- query_type: general=core topic, broad=wider/deeper class, narrow=specific mechanism,
  mechanism=molecular/cellular pathway, system=model organism/system
- Each strategy must have 2-4 synonym groups with 4-10 terms each
- Include synonyms, broader/narrower terms, spelling variants (UK/US),
  acronyms, and closely related concepts
- For biomedical topics: include taxa names, chemical names, pathway terms,
  experimental method terms, disease/model terms
- For non-biomedical topics: adapt accordingly with domain-specific terminology
- Inclusion/exclusion criteria should be specific and actionable"""


HIERARCHY_PROMPT = """You are an expert at building research concept hierarchies.

Given a topic sentence, analyze its conceptual structure and return a hierarchy.

Return ONLY valid JSON:
{
  "parent_concepts": ["wider category 1", "wider category 2"],
  "sibling_concepts": ["related but distinct topic 1", "topic 2"],
  "variants": ["alternative phrasing 1", "narrower subtopic 1"],
  "mechanism_anchors": ["molecular target 1", "pathway 1", "process 1"],
  "method_anchors": ["methodology 1", "assay 1", "model system 1"],
  "outcome_anchors": ["measured outcome 1", "phenotype 1"]
}"""


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def expand_topic(
    topic: str,
    api_key: str | None = None,
    api_type: str = "anthropic",
    model: str = "",
) -> list[Strategy]:
    """Expand a topic sentence into multiple search strategies.

    Attempts LLM expansion first, falls back to heuristic keyword extraction.
    """
    strategies = _try_llm(topic, api_key, api_type, model)
    if strategies:
        return strategies

    logger.info("LLM expansion unavailable, using heuristic")
    return expand_heuristic(topic)


def expand_heuristic(topic: str) -> list[Strategy]:
    """Keyword-based expansion without external API."""
    terms = _extract_key_terms(topic)

    # Strategy 1: whole topic
    groups: list[SynonymGroup] = []
    if terms:
        groups.append(SynonymGroup(concept="primary", terms=tuple(terms[:6])))

    strategies = [
        Strategy(
            core_query=topic,
            synonym_groups=tuple(groups),
            databases=("crossref", "pubmed", "openalex"),
            query_type="general",
        ),
    ]

    # Strategy 2: first few terms as a focused query
    if len(terms) >= 3:
        focused = Strategy(
            core_query=" ".join(terms[:3]),
            synonym_groups=(),
            databases=("pubmed", "crossref"),
            query_type="narrow",
        )
        strategies.append(focused)

    # Strategy 3: broader — just the most unique term
    if len(terms) >= 2:
        # Pick the longest term as the most specific concept
        specific = max(terms, key=len)
        strategies.append(
            Strategy(
                core_query=specific,
                synonym_groups=(),
                databases=("crossref", "openalex"),
                query_type="broad",
            )
        )

    return strategies


# ---------------------------------------------------------------------------
# 主题层次
# ---------------------------------------------------------------------------


def build_hierarchy(
    topic: str,
    api_key: str | None = None,
    api_type: str = "anthropic",
) -> dict[str, list[str]] | None:
    """Build a concept hierarchy for the topic using LLM."""
    key = _resolve_api_key(api_key, api_type)
    if not key:
        return None

    try:
        if api_type == "anthropic":
            import anthropic

            client = anthropic.Anthropic(api_key=key)
            model = "claude-sonnet-4-20250514"
            resp = client.messages.create(
                model=model,
                max_tokens=1024,
                system=HIERARCHY_PROMPT,
                messages=[{"role": "user", "content": f"Topic: {topic}"}],
            )
            raw = _extract_text(resp.content)
        elif api_type == "deepseek":
            from openai import OpenAI

            client = OpenAI(api_key=key, base_url="https://api.deepseek.com/v1")
            model = "deepseek-chat"
            resp = client.chat.completions.create(
                model=model,
                max_tokens=1024,
                messages=[
                    {"role": "system", "content": HIERARCHY_PROMPT},
                    {"role": "user", "content": f"Topic: {topic}"},
                ],
            )
            raw = resp.choices[0].message.content or ""
        else:
            from openai import OpenAI

            client = OpenAI(api_key=key)
            model = "gpt-4o"
            resp = client.chat.completions.create(
                model=model,
                max_tokens=1024,
                messages=[
                    {"role": "system", "content": HIERARCHY_PROMPT},
                    {"role": "user", "content": f"Topic: {topic}"},
                ],
            )
            raw = resp.choices[0].message.content or ""

        parsed = _parse_json(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception as e:
        logger.debug("Hierarchy build failed: %s", e)
    return None


# ---------------------------------------------------------------------------
# LLM 调用
# ---------------------------------------------------------------------------


def _try_llm(topic: str, api_key: str | None, api_type: str, model: str) -> list[Strategy]:
    """Try LLM-based expansion, return None on failure."""
    key = (
        api_key
        or os.environ.get("ANTHROPIC_API_KEY", "")
        or os.environ.get("OPENAI_API_KEY", "")
        or os.environ.get("DEEPSEEK_API_KEY", "")
    )
    if not key:
        return []

    try:
        if api_type == "anthropic":
            if not (api_key or os.environ.get("ANTHROPIC_API_KEY", "")):
                return []
            raw = _call_anthropic(topic, api_key, model)
        elif api_type == "deepseek":
            raw = _call_deepseek(topic, api_key, model)
        else:
            raw = _call_openai(topic, api_key, model)

        if not raw:
            return []
        return _parse_strategies(raw)
    except Exception as e:
        logger.warning("LLM expansion failed: %s", e)
        return []


def _call_anthropic(topic: str, api_key: str | None, model: str) -> str:
    key = api_key or os.environ["ANTHROPIC_API_KEY"]
    import anthropic

    client = anthropic.Anthropic(api_key=key)
    model_name = model or "claude-sonnet-4-20250514"
    resp = client.messages.create(
        model=model_name,
        max_tokens=3072,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Research topic: {topic}"}],
    )
    return _extract_text(resp.content)


def _call_openai(topic: str, api_key: str | None, model: str) -> str:
    key = api_key or os.environ["OPENAI_API_KEY"]
    from openai import OpenAI

    client = OpenAI(api_key=key)
    model_name = model or "gpt-4o"
    resp = client.chat.completions.create(
        model=model_name,
        max_tokens=3072,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Research topic: {topic}"},
        ],
    )
    return resp.choices[0].message.content or ""


def _call_deepseek(topic: str, api_key: str | None, model: str) -> str:
    """Call DeepSeek API (OpenAI-compatible, uses different base_url)."""
    key = api_key or os.environ["DEEPSEEK_API_KEY"]
    from openai import OpenAI

    client = OpenAI(api_key=key, base_url="https://api.deepseek.com/v1")
    model_name = model or "deepseek-chat"
    resp = client.chat.completions.create(
        model=model_name,
        max_tokens=3072,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Research topic: {topic}"},
        ],
    )
    return resp.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# 解析工具
# ---------------------------------------------------------------------------


def _parse_strategies(raw: str) -> list[Strategy]:
    """Parse LLM JSON response into Strategy objects."""
    parsed = _parse_json(raw)
    if not parsed:
        return []

    strategies_data = parsed.get("strategies", [parsed] if "core_query" in parsed else [])
    result: list[Strategy] = []

    for sd in strategies_data:
        groups_raw = sd.get("synonym_groups", [])
        groups = tuple(
            SynonymGroup(
                concept=g.get("concept", f"group_{i}"),
                terms=tuple(g.get("terms", [])[:12]),
            )
            for i, g in enumerate(groups_raw)
            if g.get("terms")
        )

        result.append(
            Strategy(
                core_query=sd.get("core_query", ""),
                synonym_groups=groups,
                inclusion_criteria=tuple(sd.get("inclusion_criteria", [])),
                exclusion_criteria=tuple(sd.get("exclusion_criteria", [])),
                databases=tuple(sd.get("suggested_databases", ["crossref", "pubmed", "openalex"])),
                query_type=sd.get("query_type", "general"),
            )
        )

    return result


def _parse_json(raw: str) -> dict[str, Any] | None:
    """Parse JSON from LLM response, stripping markdown fences."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


def _extract_text(content: list[Any]) -> str:
    """Extract text from Anthropic message content blocks."""
    for block in content:
        if getattr(block, "type", "") == "text":
            return str(getattr(block, "text", ""))
    return ""


def _resolve_api_key(api_key: str | None, api_type: str) -> str:
    """Resolve API key from parameter or env var based on api_type."""
    if api_key:
        return api_key
    if api_type == "anthropic":
        return os.environ.get("ANTHROPIC_API_KEY", "")
    elif api_type == "deepseek":
        return os.environ.get("DEEPSEEK_API_KEY", "")
    else:
        return os.environ.get("OPENAI_API_KEY", "")


def _extract_key_terms(topic: str) -> list[str]:
    """Extract meaningful keywords from a topic sentence."""
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
