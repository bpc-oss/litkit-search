"""Cross-platform browser runtime helpers for Playwright/CDP workflows."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

_WINDOWS_BROWSER_CANDIDATES = [
    os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]

_UNIX_BROWSER_CANDIDATES = [
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
]


def resolve_browser_executable() -> str | None:
    """Return an existing browser executable path or ``None``."""
    explicit = os.getenv("LITKIT_BROWSER_EXECUTABLE", "").strip()
    if explicit and Path(explicit).exists():
        return explicit

    for candidate in _UNIX_BROWSER_CANDIDATES + _WINDOWS_BROWSER_CANDIDATES:
        if candidate and Path(candidate).exists():
            return candidate

    return shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chrome")


def default_profile_dir(name: str) -> Path:
    """Return the persistent profile directory for one browser workflow."""
    root = os.getenv("LITKIT_BROWSER_PROFILE_ROOT", "").strip()
    base = Path(root) if root else Path.home() / ".litkit" / "browser"
    return base / name


def browser_launch_args() -> list[str]:
    """Return extra browser flags needed by the current runtime."""
    args: list[str] = []
    if sys.platform.startswith("linux") and hasattr(os, "geteuid") and os.geteuid() == 0:
        args.append("--no-sandbox")
    return args


def spawn_process_kwargs() -> dict[str, object]:
    """Return platform-appropriate ``subprocess.Popen`` kwargs for child grouping."""
    if sys.platform == "win32":
        return {}
    return {"start_new_session": True}


def kill_process_tree(process: subprocess.Popen[bytes] | subprocess.Popen[str]) -> None:
    """Terminate a browser process and its children on both Windows and Unix."""
    if process.poll() is not None:
        return

    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
        return

    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except Exception:
        process.kill()
