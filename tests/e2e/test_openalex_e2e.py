"""End-to-end test: real OpenAlex query -> dedup -> RIS export."""
import os
import tempfile
from pathlib import Path

import pytest

from litkit.config import load_env
from litkit.core.cache import MetadataCache
from litkit.core.pipeline import Pipeline
from litkit.exporters.ris import write_ris_file


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_openalex_search_and_export():
    config = load_env()
    if not config.openalex_key and "OPENALEX_API_KEY" not in os.environ:
        pytest.skip("OPENALEX_API_KEY not set")

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    cache = MetadataCache(db_path)
    pipeline = Pipeline(config, cache)

    papers = await pipeline.search(
        "attention is all you need", sources=["openalex"], limit=5
    )

    assert len(papers) > 0
    assert any("attention" in (p.title or "").lower() for p in papers)
    assert len(papers) == len(set(p.id for p in papers))

    ris_path = Path(tempfile.gettempdir()) / "litkit_e2e_test.ris"
    write_ris_file(papers, str(ris_path))
    assert ris_path.exists()
    content = ris_path.read_text(encoding="utf-8")
    assert "TY  - " in content
    assert "ER  -" in content
    ris_path.unlink()
    cache.close()
    Path(db_path).unlink(missing_ok=True)
