"""GROBID client — extract structured metadata from PDFs.

Expects GROBID running at http://localhost:8070 (Docker).
Ref: https://grobid.readthedocs.io/
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import httpx

from litkit.core.models import Author, Paper, Venue

_NS = {
    "tei": "http://www.tei-c.org/ns/1.0",
}


class GrobidClient:
    """Client for GROBID document processing service."""

    def __init__(self, base_url: str = "http://localhost:8070"):
        self._base_url = base_url
        self._client = httpx.Client(timeout=120.0)

    def process_pdf(self, pdf_path: str | Path) -> str | None:
        """Submit a PDF for full-text processing. Returns TEI-XML string."""
        with open(pdf_path, "rb") as f:
            files = {"input": f}
            resp = self._client.post(
                f"{self._base_url}/api/processFulltextDocument",
                files=files,
            )
        if resp.status_code != 200:
            return None
        return resp.text

    def process_header(self, pdf_path: str | Path) -> str | None:
        """Process only the header/metadata of a PDF."""
        with open(pdf_path, "rb") as f:
            files = {"input": f}
            resp = self._client.post(
                f"{self._base_url}/api/processHeaderDocument",
                files=files,
            )
        if resp.status_code != 200:
            return None
        return resp.text

    def parse_references(self, tei_xml: str) -> list[Paper]:
        """Extract references from GROBID TEI-XML output."""
        root = ET.fromstring(tei_xml)
        refs = []
        for bibl in root.findall(".//tei:listBibl/tei:biblStruct", _NS):
            ref = self._parse_bibl(bibl)
            if ref is not None:
                refs.append(ref)
        return refs

    def _parse_bibl(self, bibl: Any) -> Paper | None:
        """Parse a single bibliographic entry."""
        title_el = bibl.find(".//tei:title", _NS)
        title = title_el.text.strip() if title_el is not None and title_el.text else ""

        authors = []
        for author_el in bibl.findall(".//tei:author", _NS):
            pers_name = author_el.find("tei:persName", _NS)
            if pers_name is None:
                continue
            given = pers_name.findtext("tei:forename", "", _NS) or pers_name.findtext(
                "tei:forename[@type='first']", "", _NS
            )
            family = pers_name.findtext("tei:surname", "", _NS)
            authors.append(Author(given=given.strip(), family=family.strip()))

        doi = ""
        idno_doi = bibl.find(".//tei:idno[@type='DOI']", _NS)
        if idno_doi is not None and idno_doi.text:
            doi = idno_doi.text.strip()

        # Journal / venue
        journal_el = bibl.find(".//tei:monogr/tei:title", _NS) or bibl.find(
            ".//tei:series/tei:title", _NS
        )
        venue_name = journal_el.text.strip() if journal_el is not None and journal_el.text else ""

        publisher = bibl.findtext(".//tei:publisher", "", _NS)

        # Volume, issue, pages
        imprint = bibl.find(".//tei:imprint", _NS)
        volume = (
            imprint.findtext("tei:biblScope[@unit='volume']", "", _NS)
            if imprint is not None
            else ""
        )
        issue = (
            imprint.findtext("tei:biblScope[@unit='issue']", "", _NS) if imprint is not None else ""
        )
        pages = ""
        if imprint is not None:
            for unit in ("tei:biblScope[@unit='page']", "tei:biblScope[@unit='pages']"):
                el = imprint.find(unit, _NS)
                if el is not None and el.text:
                    pages = el.text.strip()
                    break

        year = 0
        date_el = imprint.find("tei:date", _NS) if imprint is not None else None
        if date_el is not None:
            when = date_el.get("when", "")
            if when:
                year = int(when[:4])

        return Paper(
            doi=doi,
            title=title,
            authors=tuple(authors),
            venue=Venue(name=venue_name, publisher=publisher.strip()),
            year=year,
            volume=volume,
            issue=issue,
            pages=pages,
        )

    def close(self) -> None:
        self._client.close()
