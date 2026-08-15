"""Pearl growing — 从相关论文提取关键词 → 第二轮检索.

实现 review-agent 的 PearlGrowingAgent：
  - 分析高相关论文的标题/摘要/关键词
  - 提取高频、有区分度的新术语
  - 生成第二轮搜索查询
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any

from litkit.workflows.deep_search.types import Strategy, SynonymGroup

logger = logging.getLogger(__name__)

# 过滤无意义短词
STOPWORDS = {
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
    "also",
    "however",
    "thus",
    "hence",
    "therefore",
    "using",
    "based",
    "well",
    "study",
    "studies",
    "results",
    "method",
    "methods",
    "data",
    "analysis",
    "analyze",
    "show",
    "shown",
    "found",
    "demonstrate",
    "demonstrated",
    "suggest",
    "suggested",
    "indicate",
    "indicated",
    "observe",
    "observed",
    "assess",
    "assessed",
    "evaluate",
    "evaluated",
    "examine",
    "examined",
    "investigate",
    "investigated",
    "perform",
    "performed",
    "identify",
    "identified",
    "provide",
    "provided",
    "reveal",
    "revealed",
    "lead",
    "led",
    "effect",
    "effects",
    "role",
    "roles",
    "level",
    "levels",
    "change",
    "changes",
    "increase",
    "increased",
    "decrease",
    "decreased",
    "significant",
    "significantly",
    "different",
    "among",
    "compared",
    "related",
    "associated",
}

# 一些可识别为专业术语的词性模式 (domain-agnostic scientific markers)
TERM_PATTERN = re.compile(r"[A-Z][a-z]+(?:[A-Z][a-z]+)*")  # CamelCase terms


def grow(
    papers: list[dict[str, Any]],
    top_n: int = 10,
    min_term_freq: int = 2,
) -> list[str]:
    """Extract new keywords from highly relevant papers.

    Args:
        papers: List of paper dicts (from initial search results).
        top_n: Consider top N papers by citation count.
        min_term_freq: Minimum frequency for a term to be included.

    Returns:
        List of extracted keywords (sorted by significance).
    """
    # Take top cited papers (with proper content)
    ranked = sorted(
        [p for p in papers if p.get("title") or p.get("abstract")],
        key=lambda x: -x.get("citation_count", 0),
    )
    candidates = ranked[:top_n]
    if not candidates:
        return []

    # Collect text content
    text_parts: list[str] = []
    for p in candidates:
        title = (p.get("title") or "").strip()
        abstract = (p.get("abstract") or "").strip()
        keywords = list(p.get("keywords", []))

        if title:
            text_parts.append(title)
        if abstract:
            text_parts.append(abstract)
        # Keywords are gold
        if keywords:
            text_parts.extend(keywords)

    text = " ".join(text_parts)

    # Extract candidate terms
    # 1. Multi-word phrases (2-4 word ngrams that look meaningful)
    words = re.findall(r"[a-zA-Z][a-zA-Z\-]+", text.lower())
    phrases = _extract_phrases(text)

    # 2. Single words
    single_terms = [w for w in words if w not in STOPWORDS and len(w) > 3 and not w.isdigit()]

    # 3. CamelCase/MixedCase terms (often technical)
    case_terms = TERM_PATTERN.findall(text)

    # Count frequencies
    freq = Counter(single_terms)
    phrase_freq = Counter(phrases)

    # Merge and rank
    scored: dict[str, float] = {}

    # Single terms: frequency * length penalty (prefer longer, more specific)
    for term, count in freq.items():
        if count >= min_term_freq:
            exact_match = term in [w.lower() for w in case_terms]
            scored[term] = count * min(len(term) / 4, 3.0) * (1.0 + 0.5 * exact_match)

    # Multi-word phrases: boost
    for phrase, count in phrase_freq.items():
        if count >= min_term_freq:
            scored[phrase] = count * len(phrase.split()) * 1.5

    # Sort by score
    ranked_terms = sorted(scored.items(), key=lambda x: -x[1])

    return [term for term, _ in ranked_terms[:20]]


def _extract_phrases(text: str) -> list[str]:
    """Extract meaningful multi-word phrases (2-4 words)."""
    # Split into sentences, then extract noun phrase-like patterns
    sentences = re.split(r"[.!?;]", text)
    phrases: list[str] = []

    for sent in sentences:
        sent = sent.strip().lower()
        if len(sent) < 10:
            continue

        words = re.findall(r"[a-zA-Z][a-zA-Z\-]+", sent)

        # 2-4 word windows, must contain non-stopword content
        for n in [2, 3]:
            for i in range(len(words) - n + 1):
                chunk = words[i : i + n]
                # Skip if all words are stopwords
                if all(w in STOPWORDS for w in chunk):
                    continue
                # Skip if first or last is a stopword
                if chunk[0] in STOPWORDS or chunk[-1] in STOPWORDS:
                    continue
                phrase = " ".join(chunk)
                if 5 <= len(phrase) <= 60:
                    phrases.append(phrase)

    return phrases


def grow_to_strategies(keywords: list[str], topic: str) -> list[Strategy]:
    """Convert extracted keywords into new search strategies."""
    if not keywords:
        return []

    # Group keywords into strategy
    groups = [
        SynonymGroup(concept="pearl_keywords", terms=tuple(keywords[:10])),
    ]

    return [
        Strategy(
            core_query=topic,
            synonym_groups=tuple(groups),
            databases=("crossref", "pubmed", "openalex"),
            query_type="general",
        ),
    ]
