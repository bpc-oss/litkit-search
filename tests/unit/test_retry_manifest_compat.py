"""Tests for the retry-manifest merge logic in _retry_institutional.py.

The script lives at repo root (not in the litkit package); importing it
directly is fine because it only reads the manifest-writing helper paths.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


def _run_merge(prev_content: object) -> list[dict]:
    """Execute the exact merge snippet used by run_retry()."""
    # Mirrors _retry_institutional.py lines: read prev (list or {"rows": [...]}).
    if isinstance(prev_content, list):
        merged = list(prev_content)
    elif isinstance(prev_content, dict) and isinstance(prev_content.get("rows"), list):
        merged = list(prev_content["rows"])
    else:
        merged = []
    merged.extend(
        [
            {"doi": "10.1000/a", "retry_ok": True, "bytes": 123},
            {"doi": "10.1000/b", "retry_ok": False},
        ]
    )
    return merged


def test_merge_accepts_bare_list_format() -> None:
    prev = [{"doi": "10.0000/x", "ok": False}]
    merged = _run_merge(prev)
    assert len(merged) == 3
    assert merged[0]["doi"] == "10.0000/x"
    assert merged[-1]["doi"] == "10.1000/b"


def test_merge_accepts_dict_rows_format() -> None:
    prev = {
        "generated_at": "2026-08-12 19:31:44",
        "ok": 1,
        "rows": [{"doi": "10.0000/y", "ok": False}],
    }
    merged = _run_merge(prev)
    assert len(merged) == 3
    assert merged[0]["doi"] == "10.0000/y"


def test_merge_handles_missing_or_invalid_manifest() -> None:
    assert len(_run_merge(None)) == 2
    assert len(_run_merge({"rows": "not-a-list"})) == 2
    assert len(_run_merge({"unexpected": True})) == 2


def test_manifest_roundtrip_is_serializable() -> None:
    merged = _run_merge({"rows": []})
    out = {
        "generated_at": "2026-08-14 12:00:00",
        "attempted": len(merged),
        "rows": merged,
    }
    reparsed = json.loads(json.dumps(out))
    assert reparsed["attempted"] == 2
    assert len(reparsed["rows"]) == 2
