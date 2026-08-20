#!/usr/bin/env bash
# litkit-dsh installer — macOS / Linux
# Usage: ./scripts/install.sh [pypi|wheel|git] [git-url]
set -euo pipefail

SOURCE="${1:-pypi}"
GIT_URL="${2:-https://github.com/bpshil/litkit-search.git}"
PYTHON="${PYTHON:-python3}"

echo "== litkit-dsh installer (macOS/Linux) =="

# 1. Python check (>= 3.11)
if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "ERROR: $PYTHON not found. Install Python 3.11+ first." >&2
    exit 1
fi
"$PYTHON" - <<'EOF'
import sys
sys.exit(0 if sys.version_info >= (3, 11) else 1)
EOF
if [ $? -ne 0 ]; then
    echo "ERROR: need Python >= 3.11 ($("$PYTHON" --version 2>&1))" >&2
    exit 1
fi

# 2. Virtual environment
if [ ! -d .venv ]; then "$PYTHON" -m venv .venv; fi
PY=".venv/bin/python"
echo "Using venv: $PY"

# 3. Install
case "$SOURCE" in
    pypi)  "$PY" -m pip install --upgrade litkit-search ;;
    wheel) for w in dist/litkit_search-*.whl; do [ -f "$w" ] && "$PY" -m pip install "$w"; done ;;
    git)   "$PY" -m pip install "git+$GIT_URL" ;;
    *)     echo "ERROR: unknown source '$SOURCE' (use pypi|wheel|git)" >&2; exit 1 ;;
esac

# 4. Environment self-check
echo; echo "== litkit-dsh doctor =="
.venv/bin/litkit-dsh doctor
