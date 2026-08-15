"""litkit MCP server — expose litkit to any MCP-capable agent client.

Run with: ``litkit-mcp`` (after ``pip install 'litkit-search[mcp]'``).

Works with Claude Desktop, Codex, Cursor, OpenCode, DeepSeek Harness and any
other MCP client. See docs/mcp.md for per-client setup.
"""

from __future__ import annotations

import asyncio

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("litkit")


def _run(coro):
    return asyncio.run(coro)


@mcp.tool()
def litkit_search(
    query: str,
    limit: int = 20,
    sources: str = "all",
    year_from: int | None = None,
    year_to: int | None = None,
) -> list[dict]:
    """Search academic literature across 25+ sources (arXiv, PubMed, Crossref,
    Semantic Scholar, OpenAlex, DBLP, IEEE Xplore, Scopus, WoS, SSRN, ...).

    Args:
        query: the search query.
        limit: results per source (default 20).
        sources: comma-separated source names, or "all".
        year_from: optional start year filter.
        year_to: optional end year filter.

    Returns:
        A list of paper records (doi, title, year, citations_count, source, authors, ...).
    """
    from litkit.config import load_env
    from litkit.core.cache import MetadataCache
    from litkit.core.pipeline import Pipeline
    from litkit.sources import _registry

    src_list = list(_registry) if sources in ("all", "") else [s.strip() for s in sources.split(",")]
    kwargs: dict = {}
    if year_from:
        kwargs["year_from"] = year_from
    if year_to:
        kwargs["year_to"] = year_to
    papers = _run(
        Pipeline(load_env(), MetadataCache()).search(
            query, sources=src_list, limit=limit, **kwargs
        )
    )
    return [p.model_dump(mode="json") for p in papers]


@mcp.tool()
def litkit_sources() -> dict[str, dict]:
    """List all registered literature sources and whether each requires an API key."""
    from litkit.sources import all_sources

    return {name: {"requires_key": "api_key" in dir(cls)} for name, cls in all_sources().items()}


@mcp.tool()
def litkit_fetch_doi(doi: str) -> dict | None:
    """Fetch metadata for a single DOI.

    Args:
        doi: the DOI to look up, e.g. "10.1038/nature14539".

    Returns:
        The paper record, or None if not found.
    """
    from litkit.config import load_env
    from litkit.core.cache import MetadataCache
    from litkit.core.pipeline import Pipeline

    paper = _run(Pipeline(load_env(), MetadataCache()).fetch_by_doi(doi))
    return paper.model_dump(mode="json") if paper else None


@mcp.tool()
def litkit_download(query: str, limit: int = 10, sources: str = "all") -> list[dict]:
    """Search papers and attempt to download PDFs for each.

    Args:
        query: search query or DOI.
        limit: number of papers to attempt.
        sources: comma-separated source names, or "all".

    Returns:
        Per-paper records with the local download path (or null when failed).
    """
    from litkit.config import load_env
    from litkit.core.cache import MetadataCache
    from litkit.core.pipeline import Pipeline
    from litkit.sources import _registry

    src_list = list(_registry) if sources in ("all", "") else [s.strip() for s in sources.split(",")]
    pipeline = Pipeline(load_env(), MetadataCache())
    papers = _run(pipeline.search(query, sources=src_list, limit=limit))
    results = _run(pipeline.download_pdfs(papers))
    return [
        {"id": p.id, "title": p.title, "doi": p.doi, "download_path": results.get(p.id)}
        for p in papers
    ]


@mcp.tool()
def litkit_verify(manuscript_path: str) -> dict:
    """Verify references in a manuscript (docx/pdf).

    Requires anystyle (gem install anystyle) for .docx, or GROBID for .pdf —
    see docs/troubleshooting.md. Missing tools produce a readable error, never
    a silent empty result.

    Args:
        manuscript_path: path to the .docx or .pdf manuscript.

    Returns:
        {"ok": true, "count": N, "references": [...]} or {"ok": false, "error": "..."}.
    """
    from pathlib import Path

    from litkit.verify.reference_extract import extract_from_docx, extract_from_pdf

    path = Path(manuscript_path)
    try:
        if path.suffix.lower() == ".docx":
            refs = extract_from_docx(path)
        else:
            refs = extract_from_pdf(str(path))
    except Exception as exc:  # surface readable errors to the client
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "count": len(refs),
        "references": [r.model_dump(mode="json") for r in refs],
    }


@mcp.tool()
def litkit_doctor() -> list[dict]:
    """Run litkit environment self-checks.

    Returns:
        A list of {name, status, detail} — status is PASS/FAIL/WARN.
    """
    from litkit.doctor import run_checks

    return [{"name": c.name, "status": c.status, "detail": c.detail} for c in run_checks()]


def main() -> None:
    """Entry point for the ``litkit-mcp`` console script."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
