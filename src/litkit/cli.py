"""litkit CLI — search, download, verify, export, workflows."""

from __future__ import annotations

import asyncio
import io
import json
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

# Avoid UnicodeEncodeError on legacy Windows consoles (cp1252) when rendering help/output.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(errors="replace")

from litkit.config import load_env, sync_keys
from litkit.core.cache import MetadataCache
from litkit.core.pipeline import Pipeline
from litkit.sources import _registry, all_sources

app = typer.Typer(
    name="litkit",
    help="Unified academic literature search toolkit",
    rich_markup_mode=None,
)
# On Windows cp1252, wrap stdout to replace unencodable characters rather than
# crashing with UnicodeEncodeError (common in paper titles with Greek letters,
# accented characters, CJK, etc.).
_enc = getattr(sys.stdout, "encoding", "").lower()
_is_interactive = bool(getattr(sys.stdout, "isatty", lambda: False)())
if sys.platform == "win32" and _is_interactive and _enc not in ("utf-8", "utf8", "utf_8"):
    console = Console(
        file=io.TextIOWrapper(sys.stdout.buffer, encoding=_enc, errors="replace"),
        highlight=False,
    )
else:
    console = Console()


@app.callback()
def callback(
    ctx: typer.Context,
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON instead of tables"
    ),
):
    """litkit — search, download, verify, and export academic literature."""
    ctx.obj = {"json": json_output}


@app.command()
def search(
    ctx: typer.Context,
    query: str = typer.Argument(..., help="Search query"),
    sources: str = typer.Option("all", "--sources", "-s", help="Comma-separated source names"),
    limit: int = typer.Option(20, "--limit", "-l", help="Results per source"),
    year_from: int | None = typer.Option(None, "--year-from", help="Filter from year"),
    year_to: int | None = typer.Option(None, "--year-to", help="Filter to year"),
    export: str | None = typer.Option(
        None, "--export", "-e", help="Export format: ris, bibtex, json"
    ),
    output: str | None = typer.Option(None, "--output", "-o", help="Output file path"),
):
    """Search across academic sources."""
    src_list = list(_registry) if sources == "all" else [s.strip() for s in sources.split(",")]
    kwargs = {}
    if year_from:
        kwargs["year_from"] = year_from
    if year_to:
        kwargs["year_to"] = year_to

    papers = asyncio.run(_search(query, src_list, limit, **kwargs))

    if ctx.obj.get("json"):
        console.print(_papers_json(papers))
        if export:
            _do_export(papers, export, output)
        return

    if not papers:
        console.print("[yellow]No results found.[/yellow]")
        raise typer.Exit()

    table = Table(title=f"Results ({len(papers)} papers)")
    table.add_column("DOI", style="cyan")
    table.add_column("Title", style="white")
    table.add_column("Year", justify="right")
    table.add_column("Citations", justify="right")
    table.add_column("Source")
    for p in papers[:limit]:
        table.add_row(
            p.doi or "-",
            p.title[:60] + "..." if len(p.title) > 60 else p.title,
            str(p.year) if p.year else "-",
            str(p.citations_count) if p.citations_count else "-",
            p.source,
        )
    console.print(table)

    if export:
        _do_export(papers, export, output)


@app.command()
def download(
    ctx: typer.Context,
    query: str = typer.Argument(..., help="Search query or DOI"),
    limit: int = typer.Option(10, "--limit", "-l", help="Number of papers"),
    sources: str = typer.Option("all", "--sources", "-s", help="Comma-separated source names"),
):
    """Search and download PDFs."""
    src_list = list(_registry) if sources == "all" else [s.strip() for s in sources.split(",")]
    papers = asyncio.run(_search(query, src_list, limit))
    pipeline = Pipeline()
    results = asyncio.run(pipeline.download_pdfs(papers))

    if ctx.obj.get("json"):
        payload = [
            {"id": p.id, "title": p.title, "download_path": results.get(p.id)}
            for p in papers
        ]
        console.print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    table = Table(title="Downloads")
    table.add_column("Paper")
    table.add_column("Status")
    table.add_column("Path")
    for p in papers:
        path = results.get(p.id)
        status = "[green]OK[/green]" if path else "[red]Failed[/red]"
        table.add_row(p.title[:50] if p.title else "-", status, str(path) if path else "-")
    console.print(table)


@app.command(name="download-suppl")
def download_suppl_cmd(
    query: str = typer.Argument(..., help="Search query or DOI"),
    limit: int = typer.Option(10, "--limit", "-l", help="Number of papers"),
    sources: str = typer.Option("all", "--sources", "-s", help="Comma-separated source names"),
    output_dir: str | None = typer.Option(None, "--output", "-o", help="Output directory"),
):
    """Search and download supplementary materials for papers."""
    src_list = list(_registry) if sources == "all" else [s.strip() for s in sources.split(",")]
    papers = asyncio.run(_search(query, src_list, limit))

    from litkit.downloaders.supplementary import SupplementaryDownloader

    table = Table(title="Supplementary Downloads")
    table.add_column("Paper")
    table.add_column("Files")
    table.add_column("Saved To")

    async def _do():
        sd = SupplementaryDownloader()
        results = []
        try:
            for p in papers:
                d = await sd.download(p)
                if d:
                    count = len([f for f in d.iterdir() if f.is_file() and f.name != ".done"])
                    results.append((p, count, d))
                    table.add_row(
                        p.title[:50] if p.title else "-",
                        str(count),
                        str(d),
                    )
                else:
                    results.append((p, 0, None))
                    table.add_row(
                        p.title[:50] if p.title else "-",
                        "[red]0[/red]",
                        "[red]not found[/red]",
                    )

                if output_dir and d:
                    import shutil
                    for f in d.iterdir():
                        if f.is_file() and f.name != ".done":
                            shutil.copy2(str(f), output_dir)
        finally:
            await sd.close()
        return results

    results = asyncio.run(_do())
    if any(r[1] > 0 for r in results):
        console.print(table)
        total = sum(r[1] for r in results)
        console.print(f"\n[green]Downloaded {total} supplementary files[/green]")
    else:
        console.print("[yellow]No supplementary materials found.[/yellow]")


@app.command()
def verify(
    manuscript: str = typer.Argument(..., help="Path to manuscript (docx or pdf)"),
    output_dir: str = typer.Option(".", "--output", "-o", help="Output directory"),
):
    """Verify references in a manuscript."""
    from litkit.workflows.citation_audit import run

    result = asyncio.run(run(manuscript, output_dir=output_dir))

    console.print(f"[green]Audit complete:[/green] {result['total_refs']} references")
    console.print(f"  OK: {result['ok']}")
    console.print(f"  Missing fields: {result['missing_fields']}")
    console.print(f"  Inconsistent: {result['inconsistent']}")
    console.print(f"  Not found: {result['not_found']}")
    console.print(f"  Report: {result['audit_report']}")
    console.print(f"  RIS: {result['ris_file']}")


@app.command()
def export_cmd(
    input_file: str = typer.Argument(..., help="RIS, BibTeX, or JSON input"),
    format: str = typer.Option("ris", "--format", "-f", help="Output format"),
    output: str = typer.Option("output.ris", "--output", "-o", help="Output file"),
):
    """Export papers between formats."""
    console.print("[yellow]Format conversion not yet implemented.[/yellow]")


@app.command()
def workflow(
    name: str = typer.Argument(
        ..., help="Workflow name: bulk-review, citation-audit, ranked-retrieval, topic-search"
    ),
    query: str | None = typer.Option(None, "--query", "-q", help="Search query"),
    manuscript: str | None = typer.Option(None, "--manuscript", "-m", help="Manuscript path"),
    topic: str | None = typer.Option(None, "--topic", "-t", help="Research topic"),
    output: str = typer.Option(".", "--output", "-o", help="Output directory"),
    limit: int = typer.Option(100, "--limit", "-l", help="Result limit"),
    sources: str = typer.Option("all", "--sources", "-s", help="Source names"),
    download: bool = typer.Option(False, "--download", "-d", help="Download PDFs"),
    export_format: str | None = typer.Option(None, "--export", "-e", help="Export format"),
    use_llm: bool = typer.Option(
        False, "--llm", help="Use LLM for topic expansion (topic-search only)"
    ),
    min_citations: int = typer.Option(
        0, "--min-citations", "-c", help="Min citations (topic-search only)"
    ),
):
    """Run a workflow preset."""
    src_list = list(_registry) if sources == "all" else [s.strip() for s in sources.split(",")]

    if name == "bulk-review":
        if not query:
            console.print("[red]--query is required for bulk-review[/red]")
            raise typer.Exit(1)
        from litkit.workflows.bulk_review import run

        result = asyncio.run(
            run(
                query,
                sources=src_list,
                limit=limit,
                download=download,
                export=export_format or "",
                output_dir=output,
            )
        )
        console.print(f"[green]Bulk review complete:[/green] {result['total_found']} papers")

    elif name == "citation-audit":
        if not manuscript:
            console.print("[red]--manuscript is required for citation-audit[/red]")
            raise typer.Exit(1)
        from litkit.workflows.citation_audit import run

        result = asyncio.run(run(manuscript, output_dir=output))
        console.print(f"[green]Citation audit complete:[/green] {result['total_refs']} references")

    elif name == "ranked-retrieval":
        if not topic:
            console.print("[red]--topic is required for ranked-retrieval[/red]")
            raise typer.Exit(1)
        from litkit.workflows.ranked_retrieval import run

        result = asyncio.run(run(topic, top_authors=limit, download=download, sources=src_list))
        console.print(f"[green]Ranked retrieval complete:[/green] {result['total_papers']} papers")
        console.print("Top authors:")
        for a in result["top_authors"][:10]:
            console.print(f"  {a['name']}: {a['count']} papers")

    elif name == "topic-search":
        if not topic:
            console.print("[red]--topic is required for topic-search[/red]")
            raise typer.Exit(1)
        from litkit.workflows.topic_search import run

        result = asyncio.run(
            run(
                topic=topic,
                max_papers=limit,
                use_llm=use_llm,
                sources=src_list if src_list else None,
                min_citations=min_citations,
            )
        )
        console.print(
            f"[green]Topic search complete:[/green] {result['unique_papers']} unique papers"
        )
        console.print(
            f"  Strategies: {result['strategy_count']}, Queries: {len(result['queries_used'])}"
        )
        console.print(f"  Year range: {result['year_range']}")
        for p in result["papers"][:20]:
            console.print(
                f"  {p.get('year', '-')} | {p.get('citation_count', 0):4d} cites | "
                f"{p.get('doi', '-')[:35]:35s} | {p.get('title', '')[:60]}"
            )

    else:
        console.print(f"[red]Unknown workflow: {name}[/red]")
        console.print("Available: bulk-review, citation-audit, ranked-retrieval, topic-search")
        raise typer.Exit(1)


@app.command(name="topic-search")
def topic_search_cmd(
    topic: str = typer.Argument(..., help="Research topic sentence"),
    max_papers: int = typer.Option(30, "--max-papers", "-n", help="Max unique papers"),
    use_llm: bool = typer.Option(False, "--llm", help="Use LLM for query expansion"),
    api_type: str = typer.Option(
        "anthropic", "--api-type", help="LLM API type: anthropic or openai"
    ),
    min_citations: int = typer.Option(0, "--min-citations", "-c", help="Minimum citation count"),
    sources: str = typer.Option(
        "crossref,pubmed,openalex", "--sources", "-s", help="Comma-separated sources"
    ),
    output: str = typer.Option("", "--output", "-o", help="Output JSON file"),
):
    """Search literature by topic sentence — automatically expands into multiple queries."""
    from litkit.workflows.topic_search import run

    src_list = [s.strip() for s in sources.split(",")]

    result = asyncio.run(
        run(
            topic=topic,
            max_papers=max_papers,
            use_llm=use_llm,
            api_type=api_type,
            sources=src_list,
            min_citations=min_citations,
        )
    )

    console.print(f"\n[bold]Topic:[/bold] {topic}")
    console.print(f"  Strategies:  {result['strategy_count']}")
    console.print(f"  Queries:     {len(result['queries_used'])}")
    console.print(f"  Raw hits:    {result['total_raw']}")
    console.print(f"  Unique:      {result['unique_papers']}")
    console.print(f"  Year range:  {result['year_range'][0]}-{result['year_range'][1]}")
    console.print()

    table = Table(title=f"Results ({result['unique_papers']} papers)")
    table.add_column("#", justify="right")
    table.add_column("DOI", style="cyan")
    table.add_column("Title", style="white")
    table.add_column("Year", justify="right")
    table.add_column("Citations", justify="right")
    table.add_column("Source")

    for i, p in enumerate(result["papers"], 1):
        table.add_row(
            str(i),
            p.get("doi", "-")[:35],
            (
                (p.get("title", "")[:55] + "...")
                if len(p.get("title", "")) > 55
                else p.get("title", "")
            ),
            str(p.get("year", "-")),
            str(p.get("citation_count", "-")),
            p.get("source", ""),
        )
    console.print(table)

    if output:
        import json

        with open(output, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        console.print(f"[green]Saved to {output}[/green]")


@app.command(name="deep-search")
def deep_search_cmd(
    topic: str = typer.Argument(..., help="Research topic (one sentence)"),
    max_papers: int = typer.Option(50, "--max-papers", "-n", help="Max unique papers"),
    use_llm: bool = typer.Option(False, "--llm", help="Use LLM for topic expansion"),
    api_type: str = typer.Option(
        "anthropic", "--api-type", help="LLM API type: anthropic or openai"
    ),
    min_citations: int = typer.Option(0, "--min-citations", "-c", help="Minimum citation count"),
    sources: str = typer.Option(
        "crossref,pubmed,openalex", "--sources", "-s", help="Comma-separated sources"
    ),
    no_citation_chain: bool = typer.Option(
        False, "--no-citation-chain", help="Disable citation chaining"
    ),
    no_pearl: bool = typer.Option(False, "--no-pearl", help="Disable pearl growing"),
    output: str = typer.Option("", "--output", "-o", help="Output JSON file"),
):
    """Deep search: one-sentence topic → expanded queries → multi-source → ranked papers.

    自动将一句话研究主题扩展为 30-50 个搜索查询，跨多源检索，
    追踪引文网络 (后向 + 前向)，并通过"珍珠增长"从相关论文提取关键词进行第二轮检索。
    """
    from litkit.workflows.deep_search import run

    src_list = [s.strip() for s in sources.split(",")]

    result = asyncio.run(
        run(
            topic=topic,
            max_papers=max_papers,
            use_llm=use_llm,
            api_type=api_type,
            sources=src_list,
            min_citations=min_citations,
            enable_citation_chain=not no_citation_chain,
            enable_pearl_growing=not no_pearl,
        )
    )

    console.print("\n[bold]Deep Search Results[/bold]")
    console.print(f"  Topic:      {topic}")
    console.print(f"  Strategies: {result['strategy_count']}")
    console.print(f"  Queries:    {result['total_queries']}")
    console.print(f"  Raw hits:   {result['total_raw']}")
    console.print(f"  Unique:     {result['unique_papers']}")
    console.print(f"  Year range: {result['year_range'][0]}-{result['year_range'][1]}")
    console.print(f"  Citation chain: +{result['citation_chain_count']}")
    console.print(f"  Pearl growing:  +{result['pearl_growing_count']}")
    console.print(f"  Elapsed:    {result['elapsed_seconds']}s")
    console.print()

    from rich.table import Table
    table = Table(title=f"Top {len(result['papers'])} Papers")
    table.add_column("#", justify="right")
    table.add_column("DOI", style="cyan")
    table.add_column("Title", style="white")
    table.add_column("Year", justify="right")
    table.add_column("Cites", justify="right")
    table.add_column("Source")
    table.add_column("Flag")

    for i, p in enumerate(result["papers"], 1):
        flags = []
        if p.get("from_citation_chain"):
            direction = p.get("chain_direction", "cite")
            flags.append({"backward": "[ref]", "forward": "[cited]"}.get(direction, "[cite]"))
        if p.get("from_pearl_growing"):
            flags.append("[pearl]")
        flag_str = " ".join(flags)

        table.add_row(
            str(i),
            p.get("doi", "-")[:35],
            (
                (p.get("title", "")[:55] + "...")
                if len(p.get("title", "")) > 55
                else p.get("title", "")
            ),
            str(p.get("year", "-")),
            str(p.get("citation_count", "-")),
            p.get("source", ""),
            flag_str,
        )
    console.print(table)

    if output:
        import json
        with open(output, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        console.print(f"[green]Saved to {output}[/green]")


@app.command(name="zh-search")
def zh_search_cmd(
    query: str = typer.Argument(..., help="Chinese literature search query"),
    sources: str = typer.Option(
        "cnki,wanfang,cqvip,sinomed,ncpssd",
        "--sources",
        "-s",
        help="Comma-separated Chinese sources",
    ),
    output: str = typer.Option("", "--output", "-o", help="Write search targets as CSV"),
    queue: bool = typer.Option(False, "--queue", help="Append targets to acquisition queue"),
):
    """Generate SZU-authenticated Chinese literature search/download targets."""
    from litkit.chinese.acquisition import AcquisitionRequest, append_acquisition_request
    from litkit.chinese.resources import build_search_targets

    selected = [s.strip() for s in sources.split(",") if s.strip()]
    targets = build_search_targets(query, selected)
    if not targets:
        console.print("[yellow]No Chinese resources matched.[/yellow]")
        raise typer.Exit(1)

    table = Table(title=f"Chinese Search Targets ({query})")
    table.add_column("Source")
    table.add_column("Library Entry")
    table.add_column("Search URL")
    table.add_column("Access")

    for resource, search_url in targets:
        table.add_row(
            resource.label,
            resource.library_page,
            search_url,
            resource.access_note,
        )
        if queue:
            append_acquisition_request(
                AcquisitionRequest(
                    title=f"Query: {query}",
                    source=resource.name,
                    source_url=search_url,
                    reason="query_level_chinese_search_target",
                )
            )

    console.print(table)

    if output:
        import csv

        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["source", "label", "library_page", "search_url", "access_note"],
            )
            writer.writeheader()
            for resource, search_url in targets:
                writer.writerow(
                    {
                        "source": resource.name,
                        "label": resource.label,
                        "library_page": resource.library_page,
                        "search_url": search_url,
                        "access_note": resource.access_note,
                    }
                )
        console.print(f"[green]Saved to {output_path}[/green]")


@app.command()
def doctor(ctx: typer.Context):
    """Run environment self-checks (Python, deps, sources, network, optional tools)."""
    from litkit.doctor import run_checks

    checks = run_checks()
    if ctx.obj.get("json"):
        console.print(
            json.dumps(
                [{"name": c.name, "status": c.status, "detail": c.detail} for c in checks],
                ensure_ascii=False,
                indent=2,
            )
        )
        if any(c.status == "FAIL" for c in checks):
            raise typer.Exit(1)
        return

    table = Table(title="litkit doctor — environment self-check")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    fails = 0
    for c in checks:
        color = {"PASS": "green", "FAIL": "red", "WARN": "yellow"}.get(c.status, "white")
        table.add_row(c.name, f"[{color}]{c.status}[/{color}]", c.detail)
        if c.status == "FAIL":
            fails += 1
    console.print(table)
    if fails:
        raise typer.Exit(1)


@app.command()
def sources(ctx: typer.Context):
    """List available search sources."""
    if ctx.obj.get("json"):
        console.print(
            json.dumps(
                {name: {"requires_key": "api_key" in dir(cls)} for name, cls in all_sources().items()},
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    table = Table(title="Available Sources")
    table.add_column("Name")
    table.add_column("Requires Key")
    table.add_column("Status")
    for name, cls in all_sources().items():
        table.add_row(name, "Yes" if "api_key" in dir(cls) else "No", "[green]registered[/green]")
    console.print(table)


@app.command(name="sync-keys")
def sync_keys_cmd(
    api_file: str = typer.Argument(..., help="Path to API keys file"),
):
    """Sync API keys from a text file into .env."""
    count = sync_keys(api_file)
    console.print(f"[green]Synced {count} API keys to .env[/green]")


def _papers_json(papers) -> str:
    """Serialize papers to a JSON string (for --json output)."""
    return json.dumps(
        [p.model_dump(mode="json") for p in papers],
        ensure_ascii=False,
        indent=2,
    )


def _search(query, sources, limit, **kwargs):
    config = load_env()
    cache = MetadataCache()
    pipeline = Pipeline(config, cache)
    return pipeline.search(query, sources=sources, limit=limit, **kwargs)


def _do_export(papers, fmt, output_path):
    if fmt == "ris":
        from litkit.exporters.ris import write_ris_file

        path = output_path or "results.ris"
        write_ris_file(papers, path)
    elif fmt == "bibtex":
        from litkit.exporters.bibtex import write_bibtex_file

        path = output_path or "results.bib"
        write_bibtex_file(papers, path)
    elif fmt == "json":
        from litkit.exporters.csljson import write_csljson_file

        path = output_path or "results.json"
        write_csljson_file(papers, path)
    console.print(f"[green]Exported to {path}[/green]")


if __name__ == "__main__":
    app()
