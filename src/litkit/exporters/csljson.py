"""CSL-JSON exporter (citeproc schema)."""

from __future__ import annotations

import json
from typing import Any

from litkit.core.models import Paper

_TYPE_MAP = {
    "journal": "article-journal",
    "conference": "paper-conference",
    "book": "book",
    "book-chapter": "chapter",
    "report": "report",
    "thesis": "thesis",
    "preprint": "article",
    "dataset": "dataset",
    "software": "software",
    "other": "document",
}


def to_csl(paper: Paper) -> dict[str, Any]:
    venue_type = paper.venue.type.lower() if paper.venue.type else None
    csl_type = _TYPE_MAP.get(venue_type, "article-journal") if venue_type else "article-journal"
    return {
        "id": paper.doi or paper.id,
        "type": csl_type,
        "author": [
            {"given": a.given, "family": a.family} for a in paper.authors if a.family or a.given
        ],
        "title": paper.title,
        "container-title": paper.venue.name,
        "volume": paper.volume or None,
        "issue": paper.issue or None,
        "page": paper.pages or None,
        "issued": {"date-parts": [[paper.year]]} if paper.year else None,
        "DOI": paper.doi or None,
        "URL": paper.pdf_url or paper.source_url or None,
        "abstract": paper.abstract or None,
        "keyword": ", ".join(paper.keywords) if paper.keywords else None,
        "ISSN": paper.venue.issn or None,
        "publisher": paper.venue.publisher or None,
        "language": paper.language or None,
        "source": paper.source or None,
    }


def write_csljson(papers: list[Paper]) -> str:
    return json.dumps([to_csl(p) for p in papers], indent=2, ensure_ascii=False)


def write_csljson_file(papers: list[Paper], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(write_csljson(papers))
