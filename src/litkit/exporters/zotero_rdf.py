"""Zotero RDF exporter — XML format for Zotero import.

Format based on:
  http://www.zotero.org/namespaces/export
  http://purl.org/net/biblio

Usage:
  from litkit.exporters.zotero_rdf import write_zotero_rdf_file
  write_zotero_rdf_file(papers, "export.rdf")
"""

from __future__ import annotations

import io
from typing import TextIO
from xml.etree import ElementTree as ET

from litkit.core.models import Paper

_NS = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "bib": "http://purl.org/net/biblio/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "foaf": "http://xmlns.com/foaf/0.1/",
}

_TYPE_MAP = {
    "journal": "bib:Article",
    "conference": "bib:ConferenceProceedings",
    "book": "bib:Book",
    "book-chapter": "bib:BookSection",
    "thesis": "bib:Thesis",
    "report": "bib:Report",
    "preprint": "bib:Article",
    "dataset": "bib:Article",
    "other": "bib:Article",
}


def _rdf_type(paper: Paper) -> str:
    """Map internal venue type to Zotero RDF element name."""
    return (
        _TYPE_MAP.get(paper.venue.type.lower(), "bib:Article")
        if paper.venue.type
        else "bib:Article"
    )


def _make_about(paper: Paper) -> str:
    """Build the rdf:about URI for a paper."""
    if paper.doi:
        return f"http://doi.org/{paper.doi}"
    if paper.source_url:
        return paper.source_url
    return ""


def _build_rdf(papers: list[Paper]) -> ET.Element:
    """Build the full RDF XML tree for a list of papers."""
    # Register namespace prefixes for clean XML output
    for prefix, uri in _NS.items():
        ET.register_namespace(prefix, uri)

    # Root element
    rdf = ET.Element(f"{{{_NS['rdf']}}}RDF")

    for paper in papers:
        about = _make_about(paper)
        type_tag = _rdf_type(paper)

        # Strip namespace prefix for qualified element name
        bib_uri = _NS["bib"]
        local_tag = type_tag.split(":", 1)[1] if ":" in type_tag else type_tag
        article = ET.SubElement(rdf, f"{{{bib_uri}}}{local_tag}")
        if about:
            article.set(f"{{{_NS['rdf']}}}about", about)

        # Title
        if paper.title:
            title_el = ET.SubElement(article, f"{{{_NS['dc']}}}title")
            title_el.text = paper.title

        # Authors
        for author in paper.authors:
            creator = ET.SubElement(article, f"{{{_NS['dc']}}}creator")
            person = ET.SubElement(creator, f"{{{_NS['foaf']}}}Person")
            if author.family:
                surname = ET.SubElement(person, f"{{{_NS['foaf']}}}surname")
                surname.text = author.family
            if author.given:
                givenname = ET.SubElement(person, f"{{{_NS['foaf']}}}givenname")
                givenname.text = author.given

        # DOI identifier
        if paper.doi:
            identifier = ET.SubElement(article, f"{{{_NS['dc']}}}identifier")
            identifier.set(f"{{{_NS['rdf']}}}resource", f"http://doi.org/{paper.doi}")

        # Date
        if paper.year:
            date_el = ET.SubElement(article, f"{{{_NS['dc']}}}date")
            date_el.text = str(paper.year)

        # Journal
        if paper.venue.name:
            journal_el = ET.SubElement(article, f"{{{_NS['bib']}}}journal")
            journal_el.text = paper.venue.name

        # Volume
        if paper.volume:
            volume_el = ET.SubElement(article, f"{{{_NS['bib']}}}volume")
            volume_el.text = paper.volume

        # Issue
        if paper.issue:
            issue_el = ET.SubElement(article, f"{{{_NS['bib']}}}issue")
            issue_el.text = paper.issue

        # Pages
        if paper.pages:
            pages_el = ET.SubElement(article, f"{{{_NS['bib']}}}pages")
            if "-" in paper.pages:
                start, end = paper.pages.split("-", 1)
                sp = ET.SubElement(pages_el, f"{{{_NS['bib']}}}start")
                sp.text = start.strip()
                ep = ET.SubElement(pages_el, f"{{{_NS['bib']}}}end")
                ep.text = end.strip()
            else:
                sp = ET.SubElement(pages_el, f"{{{_NS['bib']}}}start")
                sp.text = paper.pages

        # Abstract
        if paper.abstract:
            abstract_el = ET.SubElement(article, f"{{{_NS['dcterms']}}}abstract")
            abstract_el.text = paper.abstract

        # Publisher
        if paper.venue.publisher:
            publisher_el = ET.SubElement(article, f"{{{_NS['dc']}}}publisher")
            publisher_el.text = paper.venue.publisher

    return rdf


def write_zotero_rdf(papers: list[Paper], file: TextIO) -> None:
    """Write papers to *file* as Zotero RDF XML."""
    tree = _build_rdf(papers)
    ET.indent(tree, space="  ")
    xml_bytes = ET.tostring(tree, encoding="unicode", xml_declaration=True)
    file.write(xml_bytes)
    file.write("\n")


def write_zotero_rdf_file(papers: list[Paper], path: str) -> None:
    """Write papers to *path* as Zotero RDF XML."""
    with open(path, "w", encoding="utf-8") as f:
        write_zotero_rdf(papers, f)


def zotero_rdf_string(papers: list[Paper]) -> str:
    """Return papers as a Zotero RDF XML string."""
    buf = io.StringIO()
    write_zotero_rdf(papers, buf)
    return buf.getvalue()
