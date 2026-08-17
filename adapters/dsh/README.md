# @bpshil/litkit-dsh

DeepSeek Harness (dsh) plugin adapter for [litkit](../README.md) — registers
`litkit_search`, `litkit_sources`, `litkit_download`, `litkit_verify`, and
`litkit_doctor` tools in any dsh profile.

## Prerequisites

- The `litkit` CLI must be installed and on the PATH of the dsh process:
  `pip install litkit-search` (the Python wheel). Run `litkit doctor` to check.

## Install

> Distribution is GitHub-only. The adapter is not yet on npm; install it from
> a local checkout of the monorepo:

```bash
git clone https://github.com/bpc-oss/litkit-search.git
cd litkit-search
dsh plugin --profile web add "adapters/dsh"      # relative to the checkout
```

> pnpm (used by `dsh plugin`) does not support `#subdirectory=` git fragments,
> so git-URL installs of this monorepo subdirectory are not supported — use a
> local path (or the npm package once published).

Restart `dsh web`. The model then sees `litkit_*` tools; guidance lives in
[SKILL.md](SKILL.md).

## Uninstall

```bash
dsh plugin --profile web remove @bpshil/litkit-dsh
```

## Notes

- The adapter shells out to `litkit <sub> --json` (zero core changes, clean
  uninstall). Missing CLI → readable error per call.
- For other agent clients (Claude, Codex, Cursor, OpenCode), use the MCP
  server instead — see [docs/mcp.md](../docs/mcp.md).
