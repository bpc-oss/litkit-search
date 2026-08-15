"""Reference extraction from docx/PDF documents.

Primary: GROBID (Docker, PDF).
Fallback: anystyle (CLI, plain text).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

from litkit.core.models import Author, Paper, Venue
from litkit.verify.grobid import GrobidClient


def extract_from_pdf(
    pdf_path: str | Path,
    grobid_url: str = "http://localhost:8070",
) -> list[Paper]:
    """Extract references from a PDF using GROBID, falling back to anystyle."""
    grobid = GrobidClient(grobid_url)
    tei = grobid.process_pdf(pdf_path)
    grobid.close()

    if tei:
        refs = grobid.parse_references(tei)
        if refs:
            return refs

    return _extract_with_anystyle(str(pdf_path))


def extract_from_docx(docx_path: str | Path) -> list[Paper]:
    """Extract references from a .docx using anystyle."""
    return _extract_with_anystyle(str(docx_path))


def _extract_with_anystyle(file_path: str) -> list[Paper]:
    """Use anystyle CLI to parse references.

    Raises RuntimeError with install guidance when anystyle is missing or
    fails, instead of silently returning an empty list (which would make a
    citation audit report "0 references" without any explanation).
    """
    if shutil.which("anystyle") is None:
        raise RuntimeError(
            "anystyle CLI not found. Install it with: gem install anystyle "
            "(see https://github.com/inukshuk/anystyle). It is required to "
            "extract references from .docx files (and PDFs when GROBID is "
            "unavailable)."
        )
    try:
        result = subprocess.run(
            ["anystyle", "parse", file_path, "--stdout"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "anystyle timed out while parsing references "
            f"(file: {file_path}). Try again or use GROBID for PDFs."
        ) from exc
    if result.returncode != 0:
        raise RuntimeError(
            "anystyle failed to parse references "
            f"(exit {result.returncode}): {(result.stderr or result.stdout or '').strip()[:500]}"
        )
    return _parse_anystyle_output(result.stdout)


def _parse_anystyle_output(output: str) -> list[Paper]:
    try:
        refs = yaml.safe_load(output)
    except yaml.YAMLError as exc:
        raise RuntimeError(
            "anystyle produced output that could not be parsed as YAML; "
            "this may indicate a corrupted document or an anystyle version "
            "incompatibility."
        ) from exc
    if not isinstance(refs, list):
        refs = [refs]
    return [p for r in refs if (p := _anystyle_ref_to_paper(r)) is not None]


def _anystyle_ref_to_paper(ref: dict[str, Any]) -> Paper | None:
    title = _first_str(ref.get("title", ""))
    authors_list = []
    for au in ref.get("author", []):
        if isinstance(au, str):
            given, family = "", au
            if "," in au:
                family, given = au.split(",", 1)
                family, given = family.strip(), given.strip()
            authors_list.append(Author(given=given, family=family))

    doi = (ref.get("doi", "") or "").replace("https://doi.org/", "")
    year_raw = ref.get("date", ref.get("year", 0))
    year = _extract_year(_first_str(year_raw))

    return Paper(
        doi=doi,
        title=title,
        authors=tuple(authors_list),
        venue=Venue(name=_first_str(ref.get("container", ref.get("journal", "")))),
        year=year,
        volume=_first_str(ref.get("volume", "")),
        issue=_first_str(ref.get("issue", ref.get("number", ""))),
        pages=_first_str(ref.get("pages", ref.get("page", ""))),
    )


def _first_str(v: Any) -> str:
    if isinstance(v, list):
        return str(v[0]) if v else ""
    return str(v) if v else ""


def _extract_year(text: str) -> int:
    m = re.search(r"\b(19|20)\d{2}\b", str(text))
    return int(m.group()) if m else 0
