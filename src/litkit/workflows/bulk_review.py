"""Workflow: bulk-review — large-scale search + download + export (review-agent)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from litkit.config import load_env
from litkit.core.cache import MetadataCache
from litkit.core.pipeline import Pipeline


async def run(
    query: str,
    sources: list[str] | None = None,
    limit: int = 100,
    download: bool = False,
    export: str = "",
    output_dir: str = ".",
    **kwargs: Any,
) -> list[dict[str, Any]]:
    config = load_env()
    cache = MetadataCache()
    pipeline = Pipeline(config, cache)

    papers = await pipeline.search(query, sources=sources, limit=limit, **kwargs)

    result = {
        "total_found": len(papers),
        "with_doi": sum(1 for p in papers if p.doi),
        "papers": [],
    }

    if download and papers:
        dl_results = await pipeline.download_pdfs(papers)
        for p in papers:
            pdf_path = dl_results.get(p.id)
            if pdf_path:
                ...

    if export:
        ext = export.lower()
        if ext == "ris":
            from litkit.exporters.ris import write_ris_file

            path = Path(output_dir) / "results.ris"
            write_ris_file(papers, str(path))
            result["export_path"] = str(path)
        elif ext == "bibtex":
            from litkit.exporters.bibtex import write_bibtex_file

            path = Path(output_dir) / "results.bib"
            write_bibtex_file(papers, str(path))
            result["export_path"] = str(path)
        elif ext == "json":
            from litkit.exporters.csljson import write_csljson_file

            path = Path(output_dir) / "results.json"
            write_csljson_file(papers, str(path))
            result["export_path"] = str(path)

    result["papers"] = [
        {"doi": p.doi, "title": p.title[:80], "year": p.year, "citations": p.citations_count}
        for p in papers
    ]
    return result
