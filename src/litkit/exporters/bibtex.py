"""BibTeX exporter."""
from __future__ import annotations

from litkit.core.models import Paper

_ENTRY_TYPES = {
    "journal": "article", "conference": "inproceedings", "book": "book",
    "book-chapter": "incollection", "report": "techreport", "thesis": "phdthesis",
    "preprint": "article", "dataset": "misc", "other": "misc",
}


def _bib_type(paper: Paper) -> str:
    return _ENTRY_TYPES.get(paper.venue.type.lower(), "article") if paper.venue.type else "article"


def _cite_key(paper: Paper) -> str:
    import re
    first = paper.authors[0].family.lower() if paper.authors else "anon"
    first = re.sub(r"[^a-z]", "", first)
    year = paper.year or 0
    title_word = ""
    if paper.title:
        words = paper.title.lower().split()
        if words:
            title_word = re.sub(r"[^a-z]", "", words[0])
    return f"{first}{year}{title_word}"[:40]


def _escape(s: str) -> str:
    return s.replace("{", "\\{").replace("}", "\\}").replace("&", "\\&")


def write_bibtex(papers: list[Paper]) -> str:
    lines = []
    for paper in papers:
        key = _cite_key(paper)
        btype = _bib_type(paper)
        lines.append(f"@{btype}{{{key},")
        if paper.authors:
            authors = " and ".join(
                f"{a.full}" if a.given else a.family for a in paper.authors
            )
            lines.append(f"  author = {{{_escape(authors)}}},")
        if paper.title:
            lines.append(f"  title = {{{_escape(paper.title)}}},")
        if paper.venue.name:
            field = "journal" if btype == "article" else "booktitle"
            lines.append(f"  {field} = {{{_escape(paper.venue.name)}}},")
        if paper.year:
            lines.append(f"  year = {{{paper.year}}},")
        if paper.volume:
            lines.append(f"  volume = {{{paper.volume}}},")
        if paper.issue:
            lines.append(f"  number = {{{paper.issue}}},")
        if paper.pages:
            lines.append(f"  pages = {{{paper.pages}}},")
        if paper.doi:
            lines.append(f"  doi = {{{paper.doi}}},")
        if paper.venue.issn:
            lines.append(f"  issn = {{{paper.venue.issn}}},")
        if paper.venue.publisher:
            lines.append(f"  publisher = {{{_escape(paper.venue.publisher)}}},")
        lines.append("}\n")
    return "\n".join(lines)


def write_bibtex_file(papers: list[Paper], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(write_bibtex(papers))
