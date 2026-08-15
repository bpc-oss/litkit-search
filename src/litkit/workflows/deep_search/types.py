"""Pydantic models for deep-search workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SynonymGroup:
    """一组同义词 / 相关术语."""

    concept: str
    terms: tuple[str, ...]


@dataclass(frozen=True)
class Strategy:
    """一个搜索策略 = 核心概念组 + 同义词组 + 纳入/排除."""

    core_query: str
    synonym_groups: tuple[SynonymGroup, ...] = ()
    inclusion_criteria: tuple[str, ...] = ()
    exclusion_criteria: tuple[str, ...] = ()
    databases: tuple[str, ...] = ("crossref", "pubmed", "openalex")
    query_type: str = "general"  # general | broad | narrow | mechanism | system


@dataclass(frozen=True)
class PaperRecord:
    """归一化的论文记录."""

    doi: str = ""
    title: str = ""
    year: int = 0
    journal: str = ""
    source: str = ""
    citation_count: int = 0
    authors: tuple[str, ...] = ()
    abstract: str = ""
    keywords: tuple[str, ...] = ()
    is_open_access: bool = False
    from_citation_chain: bool = False
    from_pearl_growing: bool = False


def paper_to_record(p: Any) -> dict[str, Any]:
    """Convert a litkit Paper / any object to flat dict."""
    return {
        "doi": getattr(p, "doi", None) or "",
        "title": getattr(p, "title", "") or "",
        "year": getattr(p, "year", 0) or 0,
        "journal": getattr(p, "journal", "") or "",
        "source": getattr(p, "source", "") or "",
        "citation_count": getattr(p, "citations_count", 0) or 0,
        "authors": tuple(a.full or a.family or str(a) for a in getattr(p, "authors", []) if a)[:8],
        "abstract": getattr(p, "abstract", "") or "",
        "keywords": tuple(getattr(p, "keywords", []) or []),
        "is_open_access": bool(getattr(p, "is_open_access", False)),
    }
