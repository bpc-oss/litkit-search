"""Unit tests for the CLI --json output helper and JSON serialization."""

from __future__ import annotations

import json

from litkit.cli import _papers_json
from litkit.core.models import Author, Paper, Venue


def _sample_paper() -> Paper:
    return Paper(
        id="test-1",
        doi="10.1000/xyz",
        title="A test paper with CJK 标题",
        year=2024,
        citations_count=42,
        source="arxiv",
        authors=[Author(given="Alice", family="Wang")],
        venue=Venue(name="Test Journal"),
    )


def test_papers_json_roundtrip():
    payload = json.loads(_papers_json([_sample_paper()]))
    assert payload[0]["doi"] == "10.1000/xyz"
    assert payload[0]["title"] == "A test paper with CJK 标题"
    assert payload[0]["year"] == 2024
    assert payload[0]["citations_count"] == 42
    assert payload[0]["authors"][0]["family"] == "Wang"
    assert payload[0]["venue"]["name"] == "Test Journal"


def test_papers_json_empty_list():
    assert json.loads(_papers_json([])) == []
