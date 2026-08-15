"""Cross-source deduplication using DOI as primary key.

Papers without a DOI fall back to (normalized_title, year, first_author)
fuzzy matching.
"""

from __future__ import annotations

from litkit.core.models import Paper, fuzzy_match


def deduplicate(papers: list[Paper]) -> list[Paper]:
    """Remove duplicates from a list of Papers, keeping the first occurrence.

    Uses DOI match first, then fuzzy match on (normalized_title, year,
    first_author). Preserves insertion order.
    """
    seen: list[Paper] = []
    for p in papers:
        if not any(fuzzy_match(p, s) for s in seen):
            seen.append(p)
    return seen


def merge_duplicates(papers: list[Paper]) -> list[Paper]:
    """Remove duplicates *and* merge extra metadata from later copies.

    When two papers match, fields that are empty in the first copy
    are filled from the second. This enriches rather than discards.
    """
    merged: list[Paper] = []
    for p in papers:
        found = None
        for i, m in enumerate(merged):
            if fuzzy_match(p, m):
                found = i
                break
        if found is not None:
            merged[found] = _merge(merged[found], p)
        else:
            merged.append(p)
    return merged


def _merge(a: Paper, b: Paper) -> Paper:
    """Merge b's data into a where a has empty fields."""
    kw = dict(a.model_dump())
    for field in kw:
        if not kw[field]:
            bval = getattr(b, field)
            kw[field] = bval
    # Combine sources
    sources = set()
    if a.source:
        sources.add(a.source)
    if b.source:
        sources.add(b.source)
    kw["source"] = "+".join(sorted(sources))
    return Paper(**kw)
