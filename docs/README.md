# Documentation

| Guide | Purpose |
|---|---|
| [install.md](install.md) | Platform install (Windows / macOS / Linux) + extras |
| [configuration.md](configuration.md) | Zero-key setup, optional keys, institutional access |
| [usage.md](usage.md) | Full CLI reference |
| [browser.md](browser.md) | Browser-assisted download chain (Node + Playwright) |
| [mcp.md](mcp.md) | MCP server for agent clients |
| [dsh-plugin.md](dsh-plugin.md) | DeepSeek Harness plugin adapter |
| [faq.md](faq.md) | Frequently asked questions |
| [troubleshooting.md](troubleshooting.md) | Common problems and fixes |

## Maintenance convention

- **English is the primary language.** New or changed pages are written in
  English first.
- Chinese translations are kept as mirrors (`docs/zh/…`) with the same
  filenames; a translation must state at its top:
  `> 中文镜像。以英文原版为准 (English is authoritative).`
- Docs review happens in the same PR as the code change that affects them
  (`docs/` changes are required for any CLI/behavior change).
