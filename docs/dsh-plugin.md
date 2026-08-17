# dsh plugin adapter

The DeepSeek Harness adapter registers litkit tools natively in any dsh
profile (web / headless / custom).

## Tools

| Tool | Purpose |
|---|---|
| `litkit_search` | Multi-source academic search (25+ sources) |
| `litkit_sources` | List sources + key requirements |
| `litkit_download` | Search + attempt PDF downloads |
| `litkit_verify` | Reference extraction from a manuscript |
| `litkit_doctor` | Environment self-check |

## Install

Prerequisites: `litkit` CLI on PATH (`pip install "litkit-search @ git+https://github.com/bpc-oss/litkit-search.git"`), Node ≥ 20.

```bash
# From a local checkout of the monorepo (GitHub-only distribution):
git clone https://github.com/bpc-oss/litkit-search.git
cd litkit-search
dsh plugin --profile web add "adapters/dsh"
dsh --profile web --dump-config      # confirm the litkit layer mounted
```

> **Note on git-URL installs**: pnpm (the engine behind `dsh plugin`) does not
> support the `#subdirectory=` fragment for git dependencies, so
> `git+https://...#subdirectory=adapters/dsh` is **not** a supported install
> path. Use a local path (or the npm package once published).

Restart `dsh web`, then ask e.g. *"search literature for retrieval-augmented
generation with litkit"*.

## Verify the install

```bash
dsh --profile web --dump-config | Select-String -Pattern "litkit"
# expect: # == @bpshil/litkit-dsh  /  - id: litkit  /  name: '@bpshil/litkit-dsh'
```

If tools report a CLI error, run `litkit_doctor` (via the tool or terminal).

## Design

- Zero core changes: the adapter shells out to `litkit <sub> --json`; the
  bundle patch only inserts one plugin row (`cordis.patch.yml`), so uninstall
  leaves no traces.
- Loaded through the same mechanism as `dsh-bash-terminal` / `dsh-genui`
  (cordis 4 named-export plugin; `@deepseek-ai/*` imports resolve against the
  dsh host installation).
- Missing CLI degrades gracefully: each call returns a readable error with
  install guidance instead of failing silently.
