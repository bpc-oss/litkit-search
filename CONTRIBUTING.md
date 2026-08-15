# Contributing

Thanks for contributing to litkit! 🎉

## Code of conduct

This project follows a [Code of Conduct](CODE_OF_CONDUCT.md). By
participating you agree to abide by its terms.

## How to contribute

- **Report bugs** → open an [issue](https://github.com/bpshil/litkit-search/issues/new?template=bug_report.md).
- **Request features / new sources** → feature request issue (template included).
- **Fix / improve** → fork, branch, commit, open a pull request.

## Development setup

```bash
git clone https://github.com/bpshil/litkit-search.git
cd litkit-search
python -m venv .venv
# Windows: .venv\Scripts\activate | macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install            # optional but recommended
```

## Quality gates (must pass before merge)

```bash
ruff check src/ adapters/mcp/ tests/
ruff format --check src/ adapters/mcp/
mypy src/
pytest tests/ -m "not e2e" -v
```

CI runs the same gates on Linux/macOS/Windows for Python 3.11–3.13.

## Adding a new source

Sources live in [`src/litkit/sources/`](src/litkit/sources/). Each source is a
self-contained module:

1. Subclass the base source (`base_search.py`) and implement `search()`.
2. Register it in the source registry (`src/litkit/sources/__init__.py`).
3. Add `litkit sources` shows it (registry-driven, automatic).
4. Add a unit test with mocked HTTP responses (`respx` is used elsewhere).
5. Update `docs/configuration.md` if the source needs a key.

## Docs

English is primary; Chinese mirrors live under `docs/zh/`. Any CLI/behavior
change must update the docs in the same PR (see `docs/README.md`).

## Legal note

This project includes shadow-library and institutional download paths as
declared functionality (see README **Legal notice**). Code changes to those
paths must preserve the declared behavior and the disclaimers.

## Commit style

- Small, focused commits; imperative subject line.
- Reference issues: `fixes #12`.
- Keep `CHANGELOG.md` updated for user-visible changes.
