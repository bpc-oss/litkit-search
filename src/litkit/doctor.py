"""litkit doctor — environment self-check.

Run with: ``litkit doctor``.
Exits nonzero if any check FAILs (WARNs are advisory only).
"""

from __future__ import annotations

import importlib
import platform
import shutil
import socket
import sys
from dataclasses import dataclass

import httpx

MIN_PYTHON = (3, 11)
CORE_DEPS = [
    "httpx",
    "pydantic",
    "typer",
    "rich",
    "orjson",
    "lxml",
    "bs4",
    "yaml",
    "dotenv",
]
OPTIONAL_KEY_ENV = [
    "SCOPUS_API_KEY",
    "WOS_API_KEY",
    "OPENALEX_API_KEY",
    "SEMANTIC_SCHOLAR_API_KEY",
    "PUBMED_API_KEY",
    "IEEE_API_KEY",
    "ACM_API_KEY",
    "SPRINGER_API_KEY",
    "SCITE_API_KEY",
    "DIMENSIONS_API_KEY",
]
_NETWORK_URLS = [
    "https://api.crossref.org/works?rows=0",
    "https://export.arxiv.org/api/query?search_query=all:litkit&max_results=1",
]
_MIN_SOURCES = 20  # the registry ships 25 sources; allow a little slack


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str  # PASS | FAIL | WARN
    detail: str


def run_checks() -> list[CheckResult]:
    """Run every health check and return the ordered results."""
    return [
        _check_python(),
        _check_platform(),
        _check_core_deps(),
        _check_sources(),
        _check_optional_keys(),
        _check_network(),
        _check_verify_tools(),
        _check_browser_chain(),
    ]


def _check_python() -> CheckResult:
    v = sys.version_info
    ok = (v.major, v.minor) >= MIN_PYTHON
    return CheckResult(
        "python",
        "PASS" if ok else "FAIL",
        f"{sys.version.split()[0]} (need >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]})",
    )


def _check_platform() -> CheckResult:
    return CheckResult(
        "platform",
        "PASS",
        f"{platform.system()} {platform.release()} ({platform.machine()})",
    )


def _check_core_deps() -> CheckResult:
    missing = [name for name in CORE_DEPS if not _importable(name)]
    if missing:
        return CheckResult("core dependencies", "FAIL", "missing: " + ", ".join(missing))
    return CheckResult("core dependencies", "PASS", f"{len(CORE_DEPS)} modules importable")


def _check_sources() -> CheckResult:
    try:
        from litkit.sources import all_sources

        count = len(all_sources())
    except Exception as exc:  # pragma: no cover - defensive
        return CheckResult("sources registry", "FAIL", f"registry error: {exc}")
    status = "PASS" if count >= _MIN_SOURCES else "WARN"
    return CheckResult("sources registry", status, f"{count} sources registered")


def _check_optional_keys() -> CheckResult:
    try:
        from litkit.config import load_env

        cfg = load_env()
    except Exception as exc:
        return CheckResult("optional API keys", "WARN", f"config load failed: {exc}")
    present = [env for env in OPTIONAL_KEY_ENV if getattr(cfg, _env_to_attr(env), "")]
    if present:
        detail = f"{len(present)} configured: {', '.join(present)}"
        return CheckResult("optional API keys", "PASS", detail)
    return CheckResult(
        "optional API keys",
        "WARN",
        "none configured — most sources work without keys (see docs/configuration.md)",
    )


def _env_to_attr(env_name: str) -> str:
    """Map an env var name to its EnvConfig field: SCOPUS_API_KEY -> scopus_key."""
    core = env_name.replace("API_KEY", "").lower().rstrip("_")
    return f"{core}_key"


def _check_network() -> CheckResult:
    try:
        with httpx.Client(timeout=5.0, follow_redirects=True) as client:
            for url in _NETWORK_URLS:
                try:
                    resp = client.get(url)
                    if resp.status_code < 500:
                        host = url.split("/")[2]
                        return CheckResult("network", "PASS", f"reachable: {host}")
                except httpx.HTTPError:
                    continue
        return CheckResult("network", "WARN", "no academic endpoint reachable (offline?)")
    except Exception as exc:  # pragma: no cover - defensive
        return CheckResult("network", "WARN", f"check error: {exc}")


def _check_verify_tools() -> CheckResult:
    notes = []
    if shutil.which("anystyle") is None:
        notes.append("anystyle CLI missing (gem install anystyle) — docx extraction unavailable")
    else:
        notes.append("anystyle CLI found")
    if _port_open("localhost", 8070):
        notes.append("GROBID reachable at localhost:8070")
    else:
        notes.append(
            "GROBID not detected at localhost:8070 (optional; e.g. docker run lfoppiano/grobid)"
        )
    return CheckResult("verify tools", "WARN", "; ".join(notes))


def _check_browser_chain() -> CheckResult:
    notes = []
    if shutil.which("node") is None:
        notes.append("node not found — browser-assisted downloads unavailable")
    else:
        notes.append("node found")
    if _importable("playwright"):
        notes.append("playwright python package installed")
    else:
        notes.append("playwright package not installed (pip install 'litkit-search[browser]')")
    return CheckResult("browser chain", "WARN", "; ".join(notes))


def _importable(module: str) -> bool:
    try:
        importlib.import_module(module)
        return True
    except ImportError:
        return False


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False
