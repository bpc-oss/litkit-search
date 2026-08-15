"""Normalization helpers for Chinese literature records."""

from __future__ import annotations

import re
import unicodedata

_SPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[\W_]+", re.UNICODE)


def normalize_chinese_key(text: str) -> str:
    """Normalize Chinese metadata for title-based matching and deduplication."""
    normalized = unicodedata.normalize("NFKC", text or "").strip().lower()
    normalized = _SPACE_RE.sub("", normalized)
    return _PUNCT_RE.sub("", normalized)


def looks_chinese(text: str) -> bool:
    """Return True if *text* contains CJK unified ideographs."""
    return any("\u4e00" <= ch <= "\u9fff" for ch in text or "")
