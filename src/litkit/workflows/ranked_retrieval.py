"""Workflow: ranked-retrieval — topic + author ranking + citation ranking (Dry-lab)."""

from __future__ import annotations

from typing import Any

from litkit.config import load_env
from litkit.core.cache import MetadataCache
from litkit.core.pipeline import Pipeline


async def run(
    topic: str,
    top_authors: int = 20,
    sort_by: str = "citations",
    download: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    config = load_env()
    cache = MetadataCache()
    pipeline = Pipeline(config, cache)
    papers = await pipeline.search(topic, limit=top_authors * 3, **kwargs)

    if sort_by == "citations":
        papers.sort(key=lambda p: p.citations_count, reverse=True)
    elif sort_by == "year":
        papers.sort(key=lambda p: p.year, reverse=True)

    author_counts: dict[str, int] = {}
    for p in papers:
        for a in p.authors:
            name = a.full or a.family
            if name:
                author_counts[name] = author_counts.get(name, 0) + 1

    top_author_list = sorted(author_counts.items(), key=lambda x: -x[1])[:top_authors]
    results = papers[: top_authors * 2]

    return {
        "topic": topic,
        "total_papers": len(papers),
        "top_authors": [{"name": n, "count": c} for n, c in top_author_list],
        "papers": [
            {
                "doi": p.doi,
                "title": p.title[:80],
                "year": p.year,
                "citations": p.citations_count,
                "authors": [a.full or a.family for a in p.authors[:5]],
            }
            for p in results
        ],
    }
