"""Query variant generator — 同义词组 → 30+ 查询字符串.

实现了 review-agent 的 combinatorial explosion：
  - 成对交叉概念 (pairwise)
  - 三组交叉概念 (triple)
  - 单概念查询 (single concept)
  - 次要术语变体 (secondary term)
  - 布尔查询 (boolean AND/OR format)
  - 扩展/收缩查询 (broad/narrow)
"""

from __future__ import annotations

import itertools
import logging

from litkit.workflows.deep_search.types import Strategy, SynonymGroup

logger = logging.getLogger(__name__)

MAX_TERMS_PER_GROUP = 8    # 每组最多用前 N 个术语
MAX_PAIRWISE = 10          # 最多生成 N 个成对组合
MAX_TRIPLE = 8             # 最多 N 个三元组合
MAX_QUERIES_TOTAL = 50     # 总查询数上限


def build_all_queries(strategies: list[Strategy]) -> list[str]:
    """从多个策略生成所有查询变体."""
    all_queries: list[str] = []
    for s in strategies:
        all_queries.extend(_build_queries_for_strategy(s))
    # 去重 + 截断
    seen: set[str] = set()
    deduped = []
    for q in all_queries:
        key = q.lower().strip()
        if key not in seen:
            seen.add(key)
            deduped.append(q)
    return deduped[:MAX_QUERIES_TOTAL]


def _build_queries_for_strategy(strategy: Strategy) -> list[str]:
    """为一个 Strategy 生成所有查询变体."""
    queries: list[str] = []
    groups = list(strategy.synonym_groups)

    # --- 0. 核心查询 ---
    if strategy.core_query:
        queries.append(strategy.core_query)

    if not groups:
        return queries

    # 截断每组术语
    truncated = [
        SynonymGroup(g.concept, g.terms[:MAX_TERMS_PER_GROUP])
        for g in groups
    ]

    # --- 1. 成对交叉概念 (pairwise) ---
    if len(truncated) >= 2:
        count = 0
        for i, j in itertools.combinations(range(len(truncated)), 2):
            if count >= MAX_PAIRWISE:
                break
            for t1 in truncated[i].terms[:4]:
                for t2 in truncated[j].terms[:4]:
                    if count >= MAX_PAIRWISE:
                        break
                    queries.append(f"{t1} {t2}")
                    count += 1

    # --- 2. 三组交叉概念 (triple) ---
    if len(truncated) >= 3:
        count = 0
        for i, j, k in itertools.combinations(range(len(truncated)), 3):
            if count >= MAX_TRIPLE:
                break
            for t1 in truncated[i].terms[:3]:
                for t2 in truncated[j].terms[:3]:
                    for t3 in truncated[k].terms[:3]:
                        if count >= MAX_TRIPLE:
                            break
                        queries.append(f"{t1} {t2} {t3}")
                        count += 1

    # --- 3. 单概念查询 (每组首个术语作为独立查询) ---
    for g in groups:
        if g.terms:
            queries.append(g.terms[0])
            # 也加核心+单概念
            if strategy.core_query:
                queries.append(f"{strategy.core_query} {g.terms[0]}")

    # --- 4. 次要术语变体 ---
    for g in groups:
        for term in g.terms[1:4]:
            queries.append(term)

    # --- 5. 布尔查询 ---
    queries.extend(_build_boolean_queries(strategy))

    return queries


def _build_boolean_queries(strategy: Strategy) -> list[str]:
    """Generate boolean AND/OR queries for PubMed-style databases."""
    groups = list(strategy.synonym_groups)
    if not groups:
        return []

    queries: list[str] = []

    # Pairwise boolean: (A OR B) AND (C OR D)
    if len(groups) >= 2:
        for i, j in itertools.combinations(range(len(groups)), 2):
            g1_terms = [t for t in groups[i].terms[:5] if " " not in t]
            g2_terms = [t for t in groups[j].terms[:5] if " " not in t]
            if g1_terms and g2_terms:
                left = "(" + " OR ".join(g1_terms) + ")"
                right = "(" + " OR ".join(g2_terms) + ")"
                queries.append(f"{left} AND {right}")

    # Triple boolean: (A OR B) AND (C OR D) AND (E OR F)
    if len(groups) >= 3:
        g = groups
        g1 = [t for t in g[0].terms[:4] if " " not in t]
        g2 = [t for t in g[1].terms[:4] if " " not in t]
        g3 = [t for t in g[2].terms[:4] if " " not in t]
        if g1 and g2 and g3:
            q = f"({' OR '.join(g1)}) AND ({' OR '.join(g2)}) AND ({' OR '.join(g3)})"
            queries.append(q)

    # All groups conjunction (most precise)
    all_terms = []
    for g in groups:
        terms = [t for t in g.terms[:3] if " " not in t]
        if terms:
            all_terms.append("(" + " OR ".join(terms) + ")")
    if len(all_terms) >= 2:
        queries.append(" AND ".join(all_terms))

    return queries


# ---------------------------------------------------------------------------
# 分层查询生成 (broad / narrow 层次)
# ---------------------------------------------------------------------------


def build_hierarchy_queries(hierarchy: dict[str, list[str]] | None) -> list[str]:
    """从概念层次树生成查询."""
    if not hierarchy:
        return []

    queries: list[str] = []
    for _category, items in hierarchy.items():
        if isinstance(items, list):
            for item in items[:5]:
                item_clean = item.strip()
                if item_clean:
                    queries.append(item_clean)
    return queries


# ---------------------------------------------------------------------------
# 珍珠增长查询生成
# ---------------------------------------------------------------------------


def build_pearl_queries(keywords: list[str]) -> list[str]:
    """从珍珠增长提取的关键词生成新查询."""
    if not keywords:
        return []

    queries: list[str] = []
    # 单关键词
    for kw in keywords[:10]:
        queries.append(kw)

    # 成对组合
    if len(keywords) >= 2:
        for i, j in itertools.combinations(range(min(len(keywords), 8)), 2):
            queries.append(f"{keywords[i]} {keywords[j]}")

    return queries[:20]
