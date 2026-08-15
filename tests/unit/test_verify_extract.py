"""Tests for reference extraction error handling (no silent empty results)."""

from __future__ import annotations

import pytest


def test_extract_with_anystyle_raises_when_cli_missing(monkeypatch):
    from litkit.verify.reference_extract import _extract_with_anystyle

    monkeypatch.setattr("litkit.verify.reference_extract.shutil.which", lambda name: None)

    with pytest.raises(RuntimeError, match="anystyle CLI not found"):
        _extract_with_anystyle("paper.docx")


def test_extract_with_anystyle_raises_on_failure(monkeypatch):
    from litkit.verify.reference_extract import _extract_with_anystyle

    class _Failed:
        returncode = 3
        stdout = ""
        stderr = "boom: cannot parse"

    monkeypatch.setattr(
        "litkit.verify.reference_extract.shutil.which", lambda name: "/usr/bin/anystyle"
    )
    monkeypatch.setattr(
        "litkit.verify.reference_extract.subprocess.run", lambda *a, **k: _Failed()
    )

    with pytest.raises(RuntimeError, match="anystyle failed"):
        _extract_with_anystyle("paper.docx")


def test_extract_from_docx_propagates_missing_tool_error(monkeypatch):
    """extract_from_docx must surface the missing-tool error, not return []."""
    from litkit.verify.reference_extract import extract_from_docx

    monkeypatch.setattr("litkit.verify.reference_extract.shutil.which", lambda name: None)

    with pytest.raises(RuntimeError, match="anystyle CLI not found"):
        extract_from_docx("paper.docx")
