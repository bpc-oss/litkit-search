"""Pydantic models for scholarly metadata.

All models use frozen=True for immutability. DOI is the primary key;
papers without a DOI get a synthetic ID from normalized title+year.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

_DOI_RE = re.compile(r"^10\.\d{4,}/.+$")


def _norm_title(title: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    t = re.sub(r"[^\w\s]", "", title).strip().lower()
    return re.sub(r"\s+", " ", t)


def paper_id(doi: str | None, title: str | None = None, year: int | None = None) -> str:
    """Stable paper identifier: DOI if available, else hash of (title, year)."""
    if doi:
        return doi.lower().strip()
    raw = f"{_norm_title(title or '')}|{year or 0}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class Author(BaseModel, frozen=True):
    """A single author."""

    given: str = ""
    family: str = ""
    orcid: str = ""

    @property
    def full(self) -> str:
        if self.given and self.family:
            return f"{self.family}, {self.given}"
        return self.family or self.given or ""


class Venue(BaseModel, frozen=True):
    """Journal, conference, or repository."""

    name: str = ""
    short_name: str = ""  # e.g. abbreviated journal name
    issn: str = ""
    eissn: str = ""
    publisher: str = ""
    type: str = ""  # journal / conference / repository / book


class Citation(BaseModel, frozen=True):
    """A citation edge with optional context."""

    citing_id: str = ""
    cited_id: str = ""
    context: str = ""  # the sentence fragment around the citation
    doi: str = ""
    is_supporting: bool | None = None


class Paper(BaseModel, frozen=True):
    """Core scholarly work model.

    The *id* field is always the DOI (lowercased) when available,
    otherwise a synthetic 16-char hex digest of (normalized_title, year).
    """

    id: str = ""
    doi: str = ""
    title: str = ""
    authors: tuple[Author, ...] = Field(default_factory=tuple)
    venue: Venue = Field(default_factory=Venue)
    year: int = 0
    volume: str = ""
    issue: str = ""
    pages: str = ""
    abstract: str = ""
    keywords: tuple[str, ...] = Field(default_factory=tuple)
    citations_count: int = 0
    references_count: int = 0
    pdf_url: str = ""
    source_url: str = ""
    source: str = ""  # which API provided this record
    oa_status: str = ""  # gold / hybrid / green / bronze / closed / unknown
    license: str = ""
    language: str = "en"
    subjects: tuple[str, ...] = Field(default_factory=tuple)
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("doi")
    @classmethod
    def _norm_doi(cls, v: str) -> str:
        return v.strip().lower() if v else v

    @model_validator(mode="after")
    def _default_id(self) -> Paper:
        if not self.id and (self.doi or self.title):
            object.__setattr__(self, "id", paper_id(self.doi, self.title, self.year))
        return self

    @field_validator("title")
    @classmethod
    def _strip_title(cls, v: str) -> str:
        return v.strip() if v else v

    @field_validator("volume", "issue", "pages", mode="before")
    @classmethod
    def _str_or_empty(cls, v: str | None) -> str:
        return v or ""

    def dict_with_doi(self) -> dict[str, Any]:
        """Serialise, ensuring *id* tracks the doi field."""
        d = self.model_dump()
        d["id"] = paper_id(self.doi, self.title, self.year)
        return d


class SearchResult(BaseModel, frozen=True):
    """A page of search results from one source."""

    papers: tuple[Paper, ...] = Field(default_factory=tuple)
    total_estimated: int = 0  # total results the source reports
    page: int = 1
    source: str = ""


def normalize_doi(raw: str) -> str | None:
    """Return lowercased DOI string, or None if not parseable."""
    raw = raw.strip()
    if not raw:
        return None
    # Strip common URL prefixes
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
    raw = raw.rstrip("/.")
    if _DOI_RE.match(raw):
        return raw.lower()
    return None


def fuzzy_match(a: Paper, b: Paper) -> bool:
    """Check if two Papers likely refer to the same work.

    Uses DOI first, then (normalized_title, year, first_author_family).
    """
    if a.doi and b.doi and normalize_doi(a.doi) == normalize_doi(b.doi):
        return True
    if not a.title or not b.title:
        return False
    if _norm_title(a.title) != _norm_title(b.title):
        return False
    if a.year and b.year and a.year != b.year:
        return False
    # Optional: same first author
    a_first = a.authors[0].family if a.authors else ""
    b_first = b.authors[0].family if b.authors else ""
    return not (a_first and b_first and a_first.lower() != b_first.lower())
