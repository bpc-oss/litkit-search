"""RIS exporter — EndNote-compatible format.

Fields: TY, AU, TI, JO, JF, VL, IS, SP, EP, PY, DO, UR, AB, KW, SN, PB, LA, N1, ER
"""

from __future__ import annotations

import io
import textwrap
from typing import TextIO

from litkit.core.models import Paper

_TYPE_MAP = {
    "journal": "JOUR",
    "conference": "CONF",
    "book": "BOOK",
    "book-chapter": "CHAP",
    "report": "RPT",
    "thesis": "THES",
    "preprint": "JOUR",
    "dataset": "DATA",
    "software": "COMP",
    "other": "GEN",
}


def _ris_type(paper: Paper) -> str:
    return _TYPE_MAP.get(paper.venue.type.lower(), "JOUR") if paper.venue.type else "JOUR"


def _pages_split(pages: str) -> tuple[str, str]:
    if not pages:
        return "", ""
    if "-" in pages:
        a, b = pages.split("-", 1)
        return a.strip(), b.strip()
    return pages, ""


def write_ris(papers: list[Paper], file: TextIO) -> None:
    for paper in papers:
        file.write(f"TY  - {_ris_type(paper)}\n")
        for author in paper.authors:
            file.write(f"AU  - {author.full}\n")
        if paper.title:
            for line in textwrap.wrap(paper.title, width=100):
                file.write(f"TI  - {line}\n")
        if paper.venue.name:
            file.write(f"JO  - {paper.venue.name}\n")
        if paper.venue.short_name:
            file.write(f"JF  - {paper.venue.short_name}\n")
        if paper.volume:
            file.write(f"VL  - {paper.volume}\n")
        if paper.issue:
            file.write(f"IS  - {paper.issue}\n")
        sp, ep = _pages_split(paper.pages)
        if sp:
            file.write(f"SP  - {sp}\n")
        if ep:
            file.write(f"EP  - {ep}\n")
        if paper.year:
            file.write(f"PY  - {paper.year}\n")
        if paper.doi:
            file.write(f"DO  - {paper.doi}\n")
        if paper.pdf_url or paper.source_url:
            file.write(f"UR  - {paper.pdf_url or paper.source_url}\n")
        if paper.abstract:
            for line in textwrap.wrap(paper.abstract, width=100):
                file.write(f"AB  - {line}\n")
        for kw in paper.keywords:
            file.write(f"KW  - {kw}\n")
        if paper.venue.issn:
            file.write(f"SN  - {paper.venue.issn}\n")
        elif paper.venue.eissn:
            file.write(f"SN  - {paper.venue.eissn}\n")
        if paper.venue.publisher:
            file.write(f"PB  - {paper.venue.publisher}\n")
        if paper.language:
            file.write(f"LA  - {paper.language}\n")
        notes = "; ".join(
            f"{k}:{v}" for k, v in [("OA", paper.oa_status), ("Source", paper.source)] if v
        )
        if notes:
            file.write(f"N1  - {notes}\n")
        file.write("ER  - \n\n")


def write_ris_file(papers: list[Paper], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        write_ris(papers, f)


def ris_string(papers: list[Paper]) -> str:
    buf = io.StringIO()
    write_ris(papers, buf)
    return buf.getvalue()
