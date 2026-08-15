# MCP server — use litkit from any agent client

`litkit-search[mcp]` installs a Model Context Protocol (MCP) server
(`litkit-mcp`) exposing six tools:

| Tool | Purpose |
|---|---|
| `litkit_search` | Multi-source academic search (returns structured paper records) |
| `litkit_sources` | List the 25 sources + key requirements |
| `litkit_fetch_doi` | Fetch metadata for one DOI |
| `litkit_download` | Search + attempt PDF downloads |
| `litkit_verify` | Reference extraction from a manuscript (docx/pdf) |
| `litkit_doctor` | Environment self-check |

## Install

```bash
pip install 'litkit-search[mcp]'
litkit-mcp --help            # should print MCP server usage
```

## Claude Desktop

Edit `claude_desktop_config.json` (Claude → Settings → Developer → Edit Config):

```json
{
  "mcpServers": {
    "litkit": {
      "command": "litkit-mcp",
      "args": []
    }
  }
}
```

Restart Claude Desktop, then ask: *"search literature for X with litkit"*.

## Codex (OpenAI)

```bash
codex mcp add litkit -- litkit-mcp
# verify: codex mcp list
```

## Cursor

Project `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "litkit": {
      "command": "litkit-mcp",
      "args": []
    }
  }
}
```

## OpenCode

`opencode.json`:

```json
{
  "mcp": {
    "litkit": {
      "type": "stdio",
      "command": "litkit-mcp",
      "args": []
    }
  }
}
```

## DeepSeek Harness (dsh web)

DSH ships the `@deepseek-ai/dsh-mcp-client` bridge plugin. Add one plugin
instance per MCP server to the profile's patch layer (e.g. append to
`~/.dsh/profiles/web/cordis.patch.yml`):

```yaml
- id: mcp-litkit
  name: '@deepseek-ai/dsh-mcp-client'
  config:
    serverName: litkit
    transport: stdio
    command: litkit-mcp
```

> Make sure `litkit-mcp` is on the PATH of the dsh process (or set `env.PATH`
> / `cwd` in the config). After a restart the model sees tools named
> `mcp__litkit__litkit_search`, etc. DSH users may prefer the dedicated plugin
> adapter instead — see [dsh-plugin.md](dsh-plugin.md).

## Notes

- **Environment**: `litkit-mcp` must run in an environment where `litkit` is
  importable (same Python/site-packages). If you installed litkit in a venv,
  point the client at `<venv>/bin/litkit-mcp` or activate the venv first.
- **Verify tool**: reference extraction needs anystyle/GROBID — see
  [troubleshooting.md](troubleshooting.md). Missing tools return a readable
  error, never a silent empty result.
- **Search results** are returned as structured JSON (DOI, title, year,
  citations, source, authors, …) — no parsing required.
