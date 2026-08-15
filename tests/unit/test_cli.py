"""Tests for the litkit Typer CLI."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from typer.testing import CliRunner

from litkit.cli import app
from litkit.core.models import Paper

runner = CliRunner()


def test_search_default(monkeypatch):
    """Search with default options returns a results table."""
    papers = [
        Paper(
            doi="10.1234/test.1",
            title="Test Paper Title",
            year=2024,
            citations_count=10,
            source="mock_source",
        ),
    ]

    async def mock_search(query, sources, limit, **kwargs):
        return papers

    monkeypatch.setattr("litkit.cli._search", mock_search)

    result = runner.invoke(app, ["search", "test query"])
    assert result.exit_code == 0
    assert "Test Paper Title" in result.stdout


def test_search_empty(monkeypatch):
    """Search with no results shows message and exits with code 0."""

    async def mock_search(query, sources, limit, **kwargs):
        return []

    monkeypatch.setattr("litkit.cli._search", mock_search)

    result = runner.invoke(app, ["search", "test query"])
    assert result.exit_code == 0
    assert "No results found" in result.stdout


def test_search_with_export(monkeypatch):
    """Search with --export calls the export function with the right format."""
    papers = [
        Paper(
            doi="10.1234/test.2",
            title="Exportable Paper",
            year=2024,
            source="mock_source",
        ),
    ]

    async def mock_search(query, sources, limit, **kwargs):
        return papers

    export_args = []

    def mock_export(papers_arg, fmt, output_path):
        export_args.append((fmt, output_path))

    monkeypatch.setattr("litkit.cli._search", mock_search)
    monkeypatch.setattr("litkit.cli._do_export", mock_export)

    # --export ris without --output
    result = runner.invoke(app, ["search", "test", "--export", "ris"])
    assert result.exit_code == 0
    assert len(export_args) == 1
    fmt, out_path = export_args[0]
    assert fmt == "ris"
    assert out_path is None

    # --export bibtex with explicit --output
    export_args.clear()
    result = runner.invoke(
        app,
        [
            "search",
            "test",
            "--export",
            "bibtex",
            "--output",
            "out.bib",
        ],
    )
    assert result.exit_code == 0
    assert len(export_args) == 1
    fmt, out_path = export_args[0]
    assert fmt == "bibtex"
    assert out_path == "out.bib"


def test_download(monkeypatch):
    """Download command searches and downloads PDFs, showing status table."""
    papers = [
        Paper(
            doi="10.1234/test.3",
            title="Downloadable Paper",
            year=2024,
            source="mock_source",
        ),
    ]

    async def mock_search(query, sources, limit, **kwargs):
        return papers

    mock_results = {papers[0].id: Path("/tmp/test.pdf")}
    mock_pipeline = MagicMock()
    mock_pipeline.download_pdfs = AsyncMock(return_value=mock_results)

    monkeypatch.setattr("litkit.cli._search", mock_search)
    monkeypatch.setattr("litkit.cli.Pipeline", MagicMock(return_value=mock_pipeline))

    result = runner.invoke(app, ["download", "test query"])
    assert result.exit_code == 0
    assert "Downloadable Paper" in result.stdout
    assert "OK" in result.stdout


def test_sources(monkeypatch):
    """Sources command lists registered source plugins."""

    class MockSource:
        name = "mock_source"

    class MockKeySource:
        name = "mock_key_source"
        api_key = "some_key"

    monkeypatch.setattr(
        "litkit.cli.all_sources",
        lambda: {
            "mock_source": MockSource,
            "mock_key_source": MockKeySource,
        },
    )

    result = runner.invoke(app, ["sources"])
    assert result.exit_code == 0
    assert "mock_source" in result.stdout
    assert "mock_key_source" in result.stdout
    assert "registered" in result.stdout


def test_sync_keys(monkeypatch):
    """Sync-keys command reports number of synced keys."""
    monkeypatch.setattr("litkit.cli.sync_keys", lambda f: 3)

    result = runner.invoke(app, ["sync-keys", "dummy.txt"])
    assert result.exit_code == 0
    assert "Synced 3 API keys" in result.stdout


def test_workflow_unknown():
    """Unknown workflow name prints error and exits with code 1."""
    result = runner.invoke(app, ["workflow", "invalid-name"])
    assert result.exit_code == 1
    assert "Unknown workflow" in result.stdout


def test_workflow_bulk_review_no_query():
    """Bulk-review workflow exits with error when --query is missing."""
    result = runner.invoke(app, ["workflow", "bulk-review"])
    assert result.exit_code == 1
    assert "--query is required" in result.stdout


def test_help_text_has_no_mojibake():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Unified academic literature search toolkit" in result.stdout
    assert "Options:" in result.stdout
    assert "Commands:" in result.stdout
    assert "topic sentence" in result.stdout
    assert "deep search" in result.stdout.lower()
    assert "岫" not in result.stdout
    assert "弩" not in result.stdout
