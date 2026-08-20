# Installation Guide

litkit-dsh requires **Python 3.11 or newer** and works on Windows, macOS, and Linux.

## 1. Prerequisites

```bash
python --version    # need 3.11+; if missing, install from python.org / Homebrew / your distro
```

- **Windows**: install from [python.org](https://www.python.org/downloads/) (tick *Add Python to PATH*).
  Avoid the Microsoft Store alias if you hit weird PATH issues.
- **macOS**: `brew install python@3.12` (installs Xcode CLT automatically if needed).
- **Linux (Debian/Ubuntu)**: `sudo apt install python3 python3-venv python3-pip`.
- **uv** (optional, recommended): `pip install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`.

## 2. Install

### A. From GitHub (recommended)

Current distribution is GitHub-only (PyPI publishing is planned but not yet
available):

```bash
pip install "litkit-search @ git+https://github.com/bpc-oss/litkit-search.git"
```

> Requires `git` on PATH. For a pinned version, append `@v0.1.0` to the URL.

### B. From source (development / latest)

```bash
git clone https://github.com/bpc-oss/litkit-search.git
cd litkit-search
python -m venv .venv
# Windows: .venv\Scripts\activate   |   macOS/Linux: source .venv/bin/activate
pip install .
```

### C. From a local wheel (pre-release builds)

```bash
# Windows PowerShell — globs don't expand, install each file:
Get-ChildItem dist\*.whl | ForEach-Object { pip install $_.FullName }
# macOS/Linux:
pip install dist/litkit_search-*.whl
```

### D. With uv

```bash
uv venv --python 3.11
uv pip install "litkit-search @ git+https://github.com/bpc-oss/litkit-search.git"
# or from source: uv pip install -e .
```

### E. With conda

```bash
conda create -n litkit-dsh python=3.11
conda activate litkit-dsh
pip install "litkit-search @ git+https://github.com/bpc-oss/litkit-search.git"
```

## 3. Optional extras

| Extra | Install | Provides |
|---|---|---|
| `browser` | `pip install 'litkit-search[browser]'` | Playwright for browser-assisted publisher downloads (also needs Node.js) — see [browser.md](browser.md) |
| `dev` | `pip install 'litkit-search[dev]'` | pytest / ruff / mypy / pre-commit for contributors |
| `mcp` | `pip install 'litkit-search[mcp]'` | MCP server (`litkit-mcp`) for agent clients — see [mcp.md](mcp.md) |

## 4. Verify

```bash
litkit-dsh doctor
```

You should see PASS for *python*, *core dependencies*, *sources registry*
(25 sources), and *network*. WARN entries are advisory (optional API keys,
GROBID/anystyle, browser chain). If anything FAILs, see
[troubleshooting.md](troubleshooting.md).

## 5. Configure (optional)

Most sources work with **no API keys**. To enable higher rate limits / richer
metadata, configure keys — see [configuration.md](configuration.md):

```bash
litkit-dsh sync-keys            # interactive
# or copy .env.example to .env and fill in values
```
