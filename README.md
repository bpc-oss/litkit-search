# litkit — Unified Academic Literature Search Toolkit

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/litkit-search)](https://pypi.org/project/litkit-search/)
[![CI](https://github.com/bpshil/litkit-search/actions/workflows/ci.yml/badge.svg)](https://github.com/bpshil/litkit-search/actions)

Search, download, verify, and export scholarly literature from **25+ sources**
with one CLI. Bulk retrieval with deduplication, citation audit for manuscripts,
a multi-strategy PDF download chain, and agent-client integrations (MCP + DSH).

> **Published on PyPI as `litkit-search`** (the import name and CLI stay `litkit`).

---

## Features

- **25 academic sources** — arXiv, PubMed, Crossref, Semantic Scholar, OpenAlex,
  DBLP, IEEE Xplore, Scopus, Web of Science, SSRN, bioRxiv, ChemRxiv, Zenodo,
  DOAJ, Scite, OpenCitations, ACM, BASE, CORE, Dimensions, Lens, Springer,
  ORCID, and more. **Most work out of the box with zero API keys.**
- **Bulk retrieval** with deduplication and ranked results.
- **Citation audit** (`litkit verify`) — check a manuscript's (docx/pdf)
  references against the sources.
- **PDF download chain** — open-access first, then institutional access, then
  browser-assisted and shadow-library fallbacks (see [Legal notice](#legal-notice)).
- **Export** to BibTeX / RIS / JSON.
- **Workflows** — `topic-search`, `deep-search`, `bulk-review`.
- **Chinese literature** search (`zh-search`).
- **Agent-ready** — MCP server for any agent client, plus a DeepSeek Harness
  (dsh) plugin adapter.

## Quick start

```bash
# 1. Install (Python >= 3.11)
pip install litkit-search          # after PyPI release
# or from source:
#   git clone https://github.com/bpshil/litkit-search && cd litkit-search
#   pip install .

# 2. (Optional) Configure API keys — most sources need none
litkit sync-keys                   # interactive: point to a keys file

# 3. Search
litkit search "deep learning drug discovery" --limit 20 --export ris

# 4. Run a citation audit on a manuscript
litkit verify paper.docx -o report/

# 5. Check your environment
litkit doctor
```

See [docs/install.md](docs/install.md) for platform-specific guides
(Windows / macOS / Linux) and [docs/configuration.md](docs/configuration.md)
for the full configuration reference.

## Configuration

- **Zero-key default**: arXiv, PubMed, Crossref, Semantic Scholar, OpenAlex,
  DBLP, DOAJ, Zenodo, bioRxiv and most other sources work without keys.
- **Optional keys** (enable higher rate limits / richer metadata): Scopus, WoS,
  OpenAlex, Semantic Scholar, PubMed — configure via `litkit sync-keys` or a
  `.env` file (copy `.env.example` and fill in).
- **Institutional access**: set `INSTITUTIONAL_PROXY` / `INSTITUTIONAL_DIRECT`
  in `.env` to use your university's EZProxy or on-campus/VPN access for
  publisher PDFs. You are responsible for using only access you are entitled to.
- **Chinese literature** (`zh-search`): requires institutional library access
  (e.g. SZU library); see [docs/configuration.md](docs/configuration.md).

## CLI overview

| Command | Purpose |
|---|---|
| `litkit search` | Multi-source search with dedup |
| `litkit download` | Search + download PDFs |
| `litkit download-suppl` | Download supplementary materials |
| `litkit verify` | Check references in a manuscript |
| `litkit workflow citation-audit` | Citation audit workflow |
| `litkit workflow bulk-review` | Bulk review by topic |
| `litkit topic-search` / `deep-search` | Research expansion |
| `litkit zh-search` | Chinese literature search |
| `litkit sources` | List all 25 sources + status |
| `litkit export` | Export results (BibTeX/RIS/JSON; conversion in progress) |
| `litkit doctor` | Environment self-check |

## Agent integration

litkit speaks MCP, so any MCP-capable agent client can use it:

- **MCP server** (`litkit-mcp`): works with Claude Desktop, Codex, Cursor,
  OpenCode, DeepSeek Harness, and others. See [docs/mcp.md](docs/mcp.md).
- **DeepSeek Harness plugin**: install the Cordis adapter into any dsh profile.
  See [docs/dsh-plugin.md](docs/dsh-plugin.md).

```bash
# dsh install (after release):
dsh plugin --profile web add "git+https://github.com/bpshil/litkit-search.git#subdirectory=adapters/dsh"
```

## Legal notice

This project includes download strategies that may access paywalled content:

- **Institutional access**: uses your own university credentials/VPN. Only use
  access you are entitled to, and respect your institution's terms.
- **Shadow-library fallbacks** (Sci-Hub / LibGen / Anna's Archive): included as
  a declared, optional download path. Availability varies by network, and
  accessing paywalled content this way may violate publisher terms or local law
  in your jurisdiction. **Use at your own risk; the maintainers assume no
  liability.** These paths are only engaged as a last-resort fallback and can be
  disabled via configuration.

## Roadmap

- Full BibTeX/RIS export conversion (`litkit export`).
- More sources and per-source rate-limit tuning.
- Additional agent adapters and MCP resource/prompt endpoints.
- Lazily-loaded/opt-in DNS resolution for shadow-library domains.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Adding a new source? Follow the
conventions in [`src/litkit/sources/`](src/litkit/sources/) — each source is a
self-contained module registered in the source registry.

## License

[MIT](LICENSE) © 2026 bpshil. Changelog: [CHANGELOG.md](CHANGELOG.md).
