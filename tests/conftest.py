from __future__ import annotations

import asyncio
import contextlib

import pytest


@pytest.fixture(autouse=True)
def close_default_event_loop():
    yield
    with contextlib.suppress(RuntimeError):
        loop = asyncio.get_event_loop_policy().get_event_loop()
        if not loop.is_closed():
            loop.close()
    asyncio.set_event_loop(None)


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """Point every cache (PDFs, supplementary, SQLite default) at a temp dir.

    Without this, downloader unit tests write mock PDF bodies into the real
    ``~/.litkit/pdfs`` cache, which then makes later real downloads believe
    the paper is already cached (fast-path returns a 17-byte fake).
    """
    monkeypatch.setenv("LITKIT_CACHE_DIR", str(tmp_path / ".litkit"))
    yield
