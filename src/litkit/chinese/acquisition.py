"""Acquisition queue support for Chinese literature."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from litkit.core.models import Paper


@dataclass(frozen=True)
class AcquisitionRequest:
    """A full-text request that needs authenticated or manual handling."""

    title: str
    source: str
    source_url: str
    doi: str = ""
    year: int = 0
    venue: str = ""
    reason: str = "manual_or_authenticated_access_required"


def default_queue_path() -> Path:
    path = Path.home() / ".litkit" / "chinese_acquisition_queue.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def request_from_paper(
    paper: Paper,
    reason: str = "manual_or_authenticated_access_required",
) -> AcquisitionRequest:
    return AcquisitionRequest(
        title=paper.title,
        source=paper.source,
        source_url=paper.source_url or paper.pdf_url,
        doi=paper.doi,
        year=paper.year,
        venue=paper.venue.name,
        reason=reason,
    )


def append_acquisition_request(
    request: AcquisitionRequest,
    queue_path: str | Path | None = None,
) -> Path:
    """Append *request* to the CSV acquisition queue and return its path."""
    path = Path(queue_path) if queue_path else default_queue_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["title", "source", "source_url", "doi", "year", "venue", "reason"],
        )
        if write_header:
            writer.writeheader()
        writer.writerow(
            {
                "title": request.title,
                "source": request.source,
                "source_url": request.source_url,
                "doi": request.doi,
                "year": request.year,
                "venue": request.venue,
                "reason": request.reason,
            }
        )
    return path
