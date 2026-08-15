"""Tests for config loading and API key sync."""

import tomllib
from pathlib import Path

from litkit.config import EnvConfig, find_project_root, load_env, sync_keys


def test_env_config_defaults():
    c = EnvConfig()
    assert c.openalex_key == ""
    assert c.crossref_email == ""
    assert not c.has_openalex
    assert not c.has_scopus


def test_env_config_with_values():
    c = EnvConfig(openalex_key="oa-key", scopus_key="sc-key")
    assert c.openalex_key == "oa-key"
    assert c.scopus_key == "sc-key"
    assert c.has_openalex
    assert c.has_scopus


def test_find_project_root():
    root = find_project_root()
    assert (root / "pyproject.toml").exists()


def test_load_env_with_env_file(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    monkeypatch.delenv("SCOPUS_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("OPENALEX_API_KEY=test-oa-key\nSCOPUS_API_KEY=test-scopus-key\n")
    c = load_env(tmp_path)
    assert c.openalex_key == "test-oa-key"
    assert c.scopus_key == "test-scopus-key"


def test_load_env_missing(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    monkeypatch.delenv("SCOPUS_API_KEY", raising=False)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    c = load_env(tmp_path)
    assert c.openalex_key == ""


def test_load_env_reads_runtime_root_and_browser_settings(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("LITKIT_RUNTIME_ROOT", raising=False)
    monkeypatch.delenv("LITKIT_BROWSER_EXECUTABLE", raising=False)
    monkeypatch.delenv("LITKIT_BROWSER_PROFILE_ROOT", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "LITKIT_RUNTIME_ROOT=/opt/litkit-runtime",
                "LITKIT_BROWSER_EXECUTABLE=/usr/bin/google-chrome",
                "LITKIT_BROWSER_PROFILE_ROOT=/opt/litkit-runtime/runtime/auth/browser-profiles",
            ]
        ),
        encoding="utf-8",
    )
    c = load_env(tmp_path)
    assert c.runtime_root == "/opt/litkit-runtime"
    assert c.browser_executable == "/usr/bin/google-chrome"
    assert c.browser_profile_root == "/opt/litkit-runtime/runtime/auth/browser-profiles"


def test_sync_keys(tmp_path: Path):
    api_file = tmp_path / "api_keys.txt"
    api_file.write_text("SCOPUS_API_KEY=scopus-key-123\nOPENALEX_API_KEY=openalex-key-456\n")
    env_path = str(tmp_path / ".env")
    count = sync_keys(str(api_file), env_path)
    assert count == 2
    env_content = Path(env_path).read_text()
    assert "SCOPUS_API_KEY=scopus-key-123" in env_content
    assert "OPENALEX_API_KEY=openalex-key-456" in env_content


def test_sync_keys_merges_existing(tmp_path: Path):
    api_file = tmp_path / "api_keys.txt"
    api_file.write_text("SCOPUS_API_KEY=new-key\n")
    env_path = tmp_path / ".env"
    env_path.write_text("OPENALEX_API_KEY=existing-key\nSCOPUS_API_KEY=old-key\n")
    sync_keys(str(api_file), str(env_path))
    env_content = env_path.read_text()
    assert "SCOPUS_API_KEY=new-key" in env_content
    assert "OPENALEX_API_KEY=existing-key" in env_content


def test_sync_keys_alternate_format(tmp_path: Path):
    api_file = tmp_path / "api_keys.txt"
    api_file.write_text("Scopus (Elsevier)_API: scopus-value\n")
    env_path = str(tmp_path / ".env")
    count = sync_keys(str(api_file), env_path)
    assert count == 1
    assert "SCOPUS_API_KEY=scopus-value" in Path(env_path).read_text()


def test_sync_keys_no_match(tmp_path: Path):
    api_file = tmp_path / "api_keys.txt"
    api_file.write_text("SOME_OTHER_KEY=value\n")
    count = sync_keys(str(api_file), str(tmp_path / ".env"))
    assert count == 0


def test_sync_keys_skips_comment_marker_values(tmp_path: Path):
    """Values that are just a comment marker ('KEY=#') are not synced."""
    api_file = tmp_path / "api_keys.txt"
    api_file.write_text("OPENALEX_API_KEY=#\nSCOPUS_API_KEY=real-key-123\n")
    env_path = str(tmp_path / ".env")
    count = sync_keys(str(api_file), env_path)
    assert count == 1
    env_content = Path(env_path).read_text()
    assert "SCOPUS_API_KEY=real-key-123" in env_content
    assert "OPENALEX_API_KEY=" not in env_content


def test_sync_keys_preserves_non_comment_values_in_env(tmp_path: Path):
    """Existing env lines with valid values survive a re-sync."""
    api_file = tmp_path / "api_keys.txt"
    api_file.write_text("OPENALEX_API_KEY=new-key\n")
    env_path = tmp_path / ".env"
    env_path.write_text("PUBMED_EMAIL=litkit@example.com\nOPENALEX_API_KEY=old-key\n")
    sync_keys(str(api_file), str(env_path))
    env_content = Path(env_path).read_text()
    assert "OPENALEX_API_KEY=new-key" in env_content
    assert "PUBMED_EMAIL=litkit@example.com" in env_content


def test_pyproject_includes_beautifulsoup4_for_supplementary_downloader() -> None:
    project_root = find_project_root()
    pyproject = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = pyproject["project"]["dependencies"]

    assert any(dependency.startswith("beautifulsoup4") for dependency in dependencies)
