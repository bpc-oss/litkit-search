# Publishing & releases

## Pre-publish checklist (run before every release / before going public)

1. **Secrets scan**: `gitleaks detect --source . --redact` → `no leaks found`.
2. **Tracked-files audit**: `git ls-files | grep -iE "cookie|\.env|ezproxy|\.json$|\.db$"` →
   empty (only expected files). Manually eyeball `git ls-files` for anything
   surprising.
3. **Working tree clean**: `git status --porcelain` → empty.
4. **Sensitive-word scan** (personal data):
   `grep -rniE "bpshil@qq|Administrator|Desktop\\\\|@qq\\.com" --exclude-dir={_prep,.venv-test,.git} .`
   → no hits.
5. **`.env.example` tracked, `.env` not**: `git ls-files | grep env` shows only
   `.env.example`.
6. **Build**: `uv build` → wheel + sdist; clean venv install of the wheel;
   `litkit --help` and `litkit sources` work.
7. **Tests + quality**: `pytest tests/ -m "not e2e"` green; `ruff check`;
   `ruff format --check`; `mypy src/` clean (all covered by CI).
8. **Docs**: CLI/behavior changes carry docs updates in the same PR.
9. **Third-party license audit**: review new dependencies' licenses (incl.
   non-pip: anystyle = MIT, GROBID = Apache-2.0) — document in NOTICE if needed.

## Tagged release → PyPI

`release.yml` runs on tags `v*`:

1. Bump version in `pyproject.toml` + `CHANGELOG.md`.
2. `git tag v0.1.1 && git push origin v0.1.1`.
3. CI builds artifacts, publishes to PyPI, creates a GitHub release with the
   wheel + sdist attached.

### PyPI credentials

Two options (pick one):

- **Trusted publishing (recommended)**: in PyPI project settings
  (`litkit-search`) add a pending publisher for `github.com/bpc-oss/litkit-search`,
  workflow `release.yml`, environment `release`. No token stored.
- **API token**: create a PyPI token and store it as the GitHub Actions secret
  `PYPI_API_TOKEN`, then switch `release.yml` to use it
  (pypa/gh-action-pypi-publish with `password: ${{ secrets.PYPI_API_TOKEN }}`).

## Going public

1. Run the pre-publish checklist above.
2. In GitHub: Settings → General → change visibility to **public** (owner
   confirmation).
3. Add topics: `dsh-plugin`, `literature-search`, `academic`, `mcp`, `arxiv`,
   `python`.
4. Announce (optional): Oh-My-DSH / awesome-dsh-plugin listing, release notes.
