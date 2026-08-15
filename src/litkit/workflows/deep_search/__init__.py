"""deep-search: 一句话主题 → 智能扩展 → 多源穷尽检索.

核心模块：
  strategy.py          Strategy, SynonymGroup — 搜索策略生成 (LLM / 启发式)
  ontology.py          OntologyExpander — MeSH / PubChem 本体扩展
  queries.py           QueryBuilder — 同义词组 → 布尔查询组合
  citation_graph.py    CitationGraph — 后向 + 前向引用追踪
  pearl.py             PearlGrowing — 第二轮基于关键词的扩展检索
"""

from __future__ import annotations

from litkit.workflows.deep_search.engine import run

__all__ = ["run"]
