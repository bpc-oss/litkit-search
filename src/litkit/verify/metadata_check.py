"""Metadata cross-checking against reference APIs.

Given a reference extracted from a document, verify it against multiple
sources and flag discrepancies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from litkit.config import EnvConfig, load_env
from litkit.core.models import Paper
from litkit.sources.crossref import Crossref
from litkit.sources.openalex import OpenAlex


@dataclass
class FieldCheck:
    field: str
    expected: str
    found: str
    ok: bool
    note: str = ""


@dataclass
class VerificationResult:
    status: str  # ok / missing_fields / inconsistent / not_found / unresolved
    ref_paper: Paper
    matched_paper: Paper | None = None
    field_checks: list[FieldCheck] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class MetadataChecker:
    """Cross-check reference metadata against scholarly APIs."""

    def __init__(self, config: EnvConfig | None = None):
        self._config = config or load_env()

    async def verify(self, ref: Paper) -> VerificationResult:
        matched = None

        if ref.doi:
            matched = await self._fetch_by_doi(ref.doi)
            if matched and not self._titles_plausible(ref.title, matched.title):
                return VerificationResult(
                    status="inconsistent",
                    ref_paper=ref,
                    matched_paper=matched,
                    notes=[f"DOI {ref.doi} resolved but title mismatch"],
                )

        if matched is None and ref.title:
            matched = await self._search_title(ref)

        if matched is None:
            return VerificationResult(
                status="not_found", ref_paper=ref, notes=["No matching record found"]
            )

        checks = [
            FieldCheck(
                field="doi",
                expected=ref.doi or "",
                found=matched.doi or "",
                ok=bool(ref.doi and matched.doi and ref.doi.lower() == matched.doi.lower()),
            ),
            FieldCheck(
                field="year",
                expected=str(ref.year),
                found=str(matched.year),
                ok=(ref.year == 0 or matched.year == 0 or ref.year == matched.year),
            ),
        ]
        if ref.venue.name and matched.venue.name:
            checks.append(
                FieldCheck(
                    field="venue",
                    expected=ref.venue.name,
                    found=matched.venue.name,
                    ok=ref.venue.name.lower() == matched.venue.name.lower(),
                    note="venue mismatch",
                )
            )

        missing = [c.field for c in checks if not c.found and c.expected]
        inconsistent = [c for c in checks if c.expected and c.found and not c.ok]

        if missing:
            status = "missing_fields"
        elif inconsistent:
            status = "inconsistent"
        else:
            status = "ok"

        return VerificationResult(
            status=status,
            ref_paper=ref,
            matched_paper=matched,
            field_checks=checks,
        )

    async def _fetch_by_doi(self, doi: str) -> Paper | None:
        for src_cls in [Crossref, OpenAlex]:
            src = src_cls(self._config)
            try:
                paper = await src.fetch_by_doi(doi)
                if paper is not None:
                    return paper
            except Exception:
                continue
            finally:
                await src.close()
        return None

    async def _search_title(self, ref: Paper) -> Paper | None:
        src = Crossref(self._config)
        try:
            result = await src.search(ref.title, limit=5)
            for p in result.papers:
                if p.title and ref.title and _similar(ref.title, p.title):
                    return p
        except Exception:
            pass
        finally:
            await src.close()
        return None

    @staticmethod
    def _titles_plausible(a: str, b: str) -> bool:
        return _similar(a, b)


def _similar(a: str, b: str) -> bool:
    def norm(t: str) -> str:
        return re.sub(r"[^a-z0-9]", "", t.lower())

    na, nb = norm(a), norm(b)
    if not na or not nb:
        return True
    if len(na) < 10 or len(nb) < 10:
        return na == nb
    return na == nb or (na in nb or nb in na)
