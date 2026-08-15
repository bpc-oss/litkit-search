"""Configuration and API key management.

Loads .env from project root. The sync-keys command reads from a local
API key file and writes .env (not .env.example).
"""

import os
import re
from pathlib import Path
from typing import NamedTuple

import dotenv


class EnvConfig(NamedTuple):
    """Runtime configuration loaded from environment / .env."""

    openalex_key: str = ""
    crossref_email: str = ""
    semantic_scholar_key: str = ""
    scopus_key: str = ""
    wos_key: str = ""
    pubmed_email: str = ""
    pubmed_key: str = ""
    unpaywall_email: str = ""
    citation_verifier_email: str = ""
    ieee_key: str = ""
    acm_key: str = ""
    springer_key: str = ""
    scite_key: str = ""
    dimensions_key: str = ""
    institutional_proxy: str = ""
    institutional_direct: bool = False
    institutional_cookie_file: str = ""
    chinese_acquisition_queue: str = ""
    runtime_root: str = ""
    browser_executable: str = ""
    browser_profile_root: str = ""
    browser_profile: str = ""

    @property
    def has_openalex(self) -> bool:
        return bool(self.openalex_key)

    @property
    def has_scopus(self) -> bool:
        return bool(self.scopus_key)


def find_project_root() -> Path:
    """Walk up from cwd to find the directory containing pyproject.toml."""
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        if (parent / "pyproject.toml").exists():
            return parent
    return cwd


def load_env(root: Path | None = None) -> EnvConfig:
    """Load .env from project root and return typed config."""
    root = root or find_project_root()
    dotenv.load_dotenv(root / ".env")

    return EnvConfig(
        openalex_key=os.getenv("OPENALEX_API_KEY", ""),
        crossref_email=os.getenv("CROSSREF_EMAIL", ""),
        semantic_scholar_key=os.getenv("SEMANTIC_SCHOLAR_API_KEY", ""),
        scopus_key=os.getenv("SCOPUS_API_KEY", ""),
        wos_key=os.getenv("WOS_API_KEY", ""),
        pubmed_email=os.getenv("PUBMED_EMAIL", ""),
        pubmed_key=os.getenv("PUBMED_API_KEY", ""),
        unpaywall_email=os.getenv("UNPAYWALL_EMAIL", ""),
        citation_verifier_email=os.getenv("CITATION_VERIFIER_EMAIL", ""),
        acm_key=os.getenv("ACM_API_KEY", ""),
        springer_key=os.getenv("SPRINGER_API_KEY", ""),
        ieee_key=os.getenv("IEEE_API_KEY", ""),
        scite_key=os.getenv("SCITE_API_KEY", ""),
        dimensions_key=os.getenv("DIMENSIONS_API_KEY", ""),
        institutional_proxy=os.getenv("INSTITUTIONAL_PROXY", ""),
        institutional_direct=os.getenv("INSTITUTIONAL_DIRECT", "").lower() in ("true", "1", "yes"),
        institutional_cookie_file=os.getenv("INSTITUTIONAL_COOKIE_FILE", ""),
        chinese_acquisition_queue=os.getenv("CHINESE_ACQUISITION_QUEUE", ""),
        runtime_root=os.getenv("LITKIT_RUNTIME_ROOT", ""),
        browser_executable=os.getenv("LITKIT_BROWSER_EXECUTABLE", ""),
        browser_profile_root=os.getenv("LITKIT_BROWSER_PROFILE_ROOT", ""),
        browser_profile=os.getenv("LITKIT_BROWSER_PROFILE", ""),
    )


_SYNC_PATTERNS: dict[str, str] = {
    r"SCOPUS_API_KEY[=:]\s*(\S+)": "SCOPUS_API_KEY",
    r"Scopus \(Elsevier\)_API[=:]\s*(\S+)": "SCOPUS_API_KEY",
    r"WOS_API_KEY[=:]\s*(\S+)": "WOS_API_KEY",
    r"OPENALEX_API_KEY[=:]\s*(\S+)": "OPENALEX_API_KEY",
    r"PUBMED_API_KEY[=:]\s*(\S+)": "PUBMED_API_KEY",
    r"SEMANTIC_SCHOLAR_API_KEY[=:]\s*(\S+)": "SEMANTIC_SCHOLAR_API_KEY",
    r"CORE_API_KEY[=:]\s*(\S+)": "CORE_API_KEY",
    r"CROSSREF_EMAIL[=:]\s*(\S+)": "CROSSREF_EMAIL",
    r"PUBMED_EMAIL[=:]\s*(\S+)": "PUBMED_EMAIL",
    r"UNPAYWALL_EMAIL[=:]\s*(\S+)": "UNPAYWALL_EMAIL",
    r"CITATION_VERIFIER_EMAIL[=:]\s*(\S+)": "CITATION_VERIFIER_EMAIL",
    r"SCITE_API_KEY[=:]\s*(\S+)": "SCITE_API_KEY",
    r"IEEE_API_KEY[=:]\s*(\S+)": "IEEE_API_KEY",
    r"ACM_API_KEY[=:]\s*(\S+)": "ACM_API_KEY",
    r"SPRINGER_API_KEY[=:]\s*(\S+)": "SPRINGER_API_KEY",
    r"DIMENSIONS_API_KEY[=:]\s*(\S+)": "DIMENSIONS_API_KEY",
    r"INSTITUTIONAL_PROXY[=:]\s*(\S+)": "INSTITUTIONAL_PROXY",
    r"INSTITUTIONAL_DIRECT[=:]\s*(\S+)": "INSTITUTIONAL_DIRECT",
    r"INSTITUTIONAL_COOKIE_FILE[=:]\s*(\S+)": "INSTITUTIONAL_COOKIE_FILE",
    r"CHINESE_ACQUISITION_QUEUE[=:]\s*(\S+)": "CHINESE_ACQUISITION_QUEUE",
    r"LITKIT_RUNTIME_ROOT[=:]\s*(\S+)": "LITKIT_RUNTIME_ROOT",
    r"LITKIT_BROWSER_EXECUTABLE[=:]\s*(\S+)": "LITKIT_BROWSER_EXECUTABLE",
    r"LITKIT_BROWSER_PROFILE_ROOT[=:]\s*(\S+)": "LITKIT_BROWSER_PROFILE_ROOT",
}


def sync_keys(api_file: str, env_path: str | None = None) -> int:
    """Parse *api_file* for API keys and write them into .env.

    Returns the number of keys synced.
    """
    env_path = env_path or str(find_project_root() / ".env")

    with open(api_file, encoding="utf-8") as f:
        content = f.read()

    found: dict[str, str] = {}
    for pattern, key_name in _SYNC_PATTERNS.items():
        if m := re.search(pattern, content, re.MULTILINE):
            value = m.group(1).strip()
            # Skip comment-marker or empty values (e.g. "KEY=# broken").
            if not value or value.startswith("#"):
                continue
            found[key_name] = value

    existing: dict[str, str] = {}
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    k = k.strip()
                    v = v.strip()
                    if k and v and not v.startswith("#"):
                        existing[k] = v

    existing.update(found)
    with open(env_path, "w", encoding="utf-8") as f:
        for key, value in existing.items():
            f.write(f"{key}={value}\n")

    return len(found)
