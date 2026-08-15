"""Workflow: citation-audit — verify manuscript references (academic_paper_team_rebuild)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from litkit.config import load_env
from litkit.verify.metadata_check import MetadataChecker
from litkit.verify.reference_extract import extract_from_docx, extract_from_pdf


async def run(
    manuscript: str,
    output_dir: str = ".",
    **kwargs: Any,
) -> dict[str, Any]:
    config = load_env()
    checker = MetadataChecker(config)
    path = Path(manuscript)

    if path.suffix.lower() == ".pdf":
        refs = extract_from_pdf(str(path))
    elif path.suffix.lower() == ".docx":
        refs = extract_from_docx(str(path))
    else:
        raise ValueError(f"Unsupported file type: {path.suffix}")

    results = []
    for ref in refs:
        vr = await checker.verify(ref)
        results.append(
            {
                "ref": ref.title[:80] if ref.title else "(no title)",
                "doi": ref.doi or "",
                "status": vr.status,
                "matched_doi": vr.matched_paper.doi if vr.matched_paper else "",
                "notes": vr.notes,
            }
        )

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    report_path = output_path / "references_audit.md"

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# Reference Audit Report\n\n")
        ok_count = sum(1 for r in results if r["status"] == "ok")
        f.write(f"**{ok_count}/{len(results)} references OK**\n\n")
        for r in results:
            f.write(f"## {r['status']} {r['ref']}\n")
            f.write(f"- Status: {r['status']}\n")
            f.write(f"- DOI: {r['doi']}\n")
            f.write(f"- Matched DOI: {r['matched_doi']}\n")
            if r["notes"]:
                f.write(f"- Notes: {'; '.join(r['notes'])}\n")
            f.write("\n")

    from litkit.exporters.ris import write_ris_file

    ris_path = output_path / "references.ris"
    write_ris_file(refs, str(ris_path))

    return {
        "total_refs": len(refs),
        "ok": sum(1 for r in results if r["status"] == "ok"),
        "missing_fields": sum(1 for r in results if r["status"] == "missing_fields"),
        "inconsistent": sum(1 for r in results if r["status"] == "inconsistent"),
        "not_found": sum(1 for r in results if r["status"] == "not_found"),
        "audit_report": str(report_path),
        "ris_file": str(ris_path),
        "details": results,
    }
