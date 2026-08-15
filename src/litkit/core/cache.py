"""Two-layer cache: SQLite for metadata, filesystem for PDFs.

Cache location: ~/.litkit/
  cache.db — SQLite with paper metadata, HTTP responses, audit log
  pdfs/    — downloaded PDFs keyed by DOI hash
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from litkit.core.models import Paper


def _cache_dir() -> Path:
    """Return the cache root (~/.litkit, or $LITKIT_CACHE_DIR in tests/CI)."""
    base = Path(os.environ.get("LITKIT_CACHE_DIR") or (Path.home() / ".litkit"))
    base.mkdir(parents=True, exist_ok=True)
    (base / "pdfs").mkdir(exist_ok=True)
    return base


def _doi_prefix(doi: str) -> str:
    """Return the DOI prefix segment used for downloader capability memory."""
    if not doi or "/" not in doi:
        return ""
    return f"{doi.split('/', 1)[0]}/"


class MetadataCache:
    """SQLite-backed cache for paper metadata and HTTP responses."""

    _SCHEMA = [
        """CREATE TABLE IF NOT EXISTS papers (
            id TEXT PRIMARY KEY,
            doi TEXT UNIQUE,
            data TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT '',
            cached_at INTEGER NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS http_cache (
            url_hash TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            data TEXT NOT NULL,
            cached_at INTEGER NOT NULL,
            ttl INTEGER NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            action TEXT NOT NULL,
            detail TEXT NOT NULL
        )""",
        """CREATE INDEX IF NOT EXISTS idx_http_url ON http_cache(url)""",
        """CREATE TABLE IF NOT EXISTS doi_resolution_cache (
            doi TEXT PRIMARY KEY,
            resolved_url TEXT NOT NULL,
            cached_at INTEGER NOT NULL,
            ttl INTEGER NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS downloader_memory (
            doi_prefix TEXT NOT NULL,
            downloader TEXT NOT NULL,
            successes INTEGER NOT NULL DEFAULT 0,
            failures INTEGER NOT NULL DEFAULT 0,
            last_success_ts INTEGER NOT NULL DEFAULT 0,
            last_failure_ts INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (doi_prefix, downloader)
        )""",
    ]

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            cache_dir = _cache_dir()
            self._db_path = cache_dir / "cache.db"
            self._pdf_dir = cache_dir / "pdfs"
        else:
            self._db_path = Path(db_path)
            self._pdf_dir = self._db_path.parent / f"{self._db_path.stem}-pdfs"
            self._pdf_dir.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        for stmt in self._SCHEMA:
            self._conn.execute(stmt)
        self._conn.commit()

    # ── Paper cache ──────────────────────────────────────────────

    def get_paper(self, paper_id: str) -> Paper | None:
        cur = self._conn.execute(
            "SELECT data FROM papers WHERE id = ?", (paper_id,)
        )
        row = cur.fetchone()
        if row is None:
            return None
        return Paper.model_validate_json(row[0])

    def put_paper(self, paper: Paper) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO papers (id, doi, data, source, cached_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                paper.id,
                paper.doi,
                paper.model_dump_json(),
                paper.source,
                int(time.time()),
            ),
        )
        self._conn.commit()

    def put_papers(self, papers: list[Paper]) -> None:
        now = int(time.time())
        rows = [
            (p.id, p.doi, p.model_dump_json(), p.source, now) for p in papers
        ]
        self._conn.executemany(
            "INSERT OR REPLACE INTO papers (id, doi, data, source, cached_at) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        self._conn.commit()

    def search_papers(self, query: str, limit: int = 50) -> list[Paper]:
        cur = self._conn.execute(
            "SELECT data FROM papers WHERE data LIKE ? LIMIT ?",
            (f"%{query}%", limit),
        )
        return [Paper.model_validate_json(r[0]) for r in cur.fetchall()]

    # ── HTTP cache ───────────────────────────────────────────────

    def get_http(self, url: str) -> str | None:
        url_hash = hashlib.sha256(url.encode()).hexdigest()
        cur = self._conn.execute(
            "SELECT data, cached_at, ttl FROM http_cache WHERE url_hash = ?",
            (url_hash,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        data, cached_at, ttl = row
        if time.time() - cached_at > ttl:
            self._conn.execute(
                "DELETE FROM http_cache WHERE url_hash = ?", (url_hash,)
            )
            self._conn.commit()
            return None
        return data  # type: ignore[no-any-return]

    def put_http(self, url: str, data: str, ttl: int = 3600) -> None:
        url_hash = hashlib.sha256(url.encode()).hexdigest()
        self._conn.execute(
            "INSERT OR REPLACE INTO http_cache (url_hash, url, data, cached_at, ttl) "
            "VALUES (?, ?, ?, ?, ?)",
            (url_hash, url, data, int(time.time()), ttl),
        )
        self._conn.commit()

    def get_doi_resolution(self, doi: str) -> str | None:
        cur = self._conn.execute(
            "SELECT resolved_url, cached_at, ttl FROM doi_resolution_cache WHERE doi = ?",
            (doi.lower().strip(),),
        )
        row = cur.fetchone()
        if row is None:
            return None
        resolved_url, cached_at, ttl = row
        if time.time() - cached_at > ttl:
            self._conn.execute(
                "DELETE FROM doi_resolution_cache WHERE doi = ?",
                (doi.lower().strip(),),
            )
            self._conn.commit()
            return None
        return str(resolved_url)

    def put_doi_resolution(self, doi: str, resolved_url: str, ttl: int = 86400) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO doi_resolution_cache (doi, resolved_url, cached_at, ttl) "
            "VALUES (?, ?, ?, ?)",
            (doi.lower().strip(), resolved_url, int(time.time()), ttl),
        )
        self._conn.commit()

    def record_downloader_outcome(self, doi: str, downloader: str, success: bool) -> None:
        doi_prefix = _doi_prefix(doi.lower().strip())
        if not doi_prefix:
            return
        now = int(time.time())
        self._conn.execute(
            """
            INSERT INTO downloader_memory (
                doi_prefix, downloader, successes, failures, last_success_ts, last_failure_ts
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(doi_prefix, downloader) DO UPDATE SET
                successes = successes + excluded.successes,
                failures = failures + excluded.failures,
                last_success_ts = MAX(last_success_ts, excluded.last_success_ts),
                last_failure_ts = MAX(last_failure_ts, excluded.last_failure_ts)
            """,
            (
                doi_prefix,
                downloader,
                1 if success else 0,
                0 if success else 1,
                now if success else 0,
                0 if success else now,
            ),
        )
        self._conn.commit()

    def preferred_downloaders(self, doi: str) -> list[str]:
        doi_prefix = _doi_prefix(doi.lower().strip())
        if not doi_prefix:
            return []
        cur = self._conn.execute(
            """
            SELECT downloader
            FROM downloader_memory
            WHERE doi_prefix = ?
            ORDER BY
                CASE
                    WHEN successes > 0 THEN 0
                    WHEN failures >= 2 THEN 2
                    ELSE 1
                END,
                CASE
                    WHEN successes > 0 THEN CAST(successes AS REAL) / (successes + failures)
                    ELSE 0
                END DESC,
                successes DESC,
                failures ASC,
                last_success_ts DESC,
                last_failure_ts ASC,
                downloader ASC
            """,
            (doi_prefix,),
        )
        return [str(row[0]) for row in cur.fetchall()]

    # ── Audit log ────────────────────────────────────────────────

    def audit(self, action: str, detail: str = "") -> None:
        self._conn.execute(
            "INSERT INTO audit_log (ts, action, detail) VALUES (?, ?, ?)",
            (int(time.time()), action, detail),
        )
        self._conn.commit()

    def recent_audit(self, limit: int = 50) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT ts, action, detail FROM audit_log ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [
            {"ts": r[0], "action": r[1], "detail": r[2]} for r in cur.fetchall()
        ]

    # ── PDF cache ────────────────────────────────────────────────

    def pdf_path(self, paper_id: str) -> Path:
        h = hashlib.sha256(paper_id.encode()).hexdigest()
        return self._pdf_dir / f"{h}.pdf"

    def has_pdf(self, paper_id: str) -> bool:
        return self.is_valid_pdf(self.pdf_path(paper_id))

    @staticmethod
    def is_valid_pdf(path: Path) -> bool:
        """Return whether *path* looks like a complete, non-trivial PDF."""
        try:
            if path.stat().st_size < 1024:
                return False
            with path.open("rb") as handle:
                if handle.read(5) != b"%PDF-":
                    return False
                handle.seek(max(0, path.stat().st_size - 2048))
                return b"%%EOF" in handle.read()
        except OSError:
            return False

    def close(self) -> None:
        self._conn.close()
