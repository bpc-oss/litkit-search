# FAQ

### Do I need API keys?

No. 25 sources work out of the box with zero keys. Keys (Scopus, WoS, OpenAlex,
Semantic Scholar, PubMed…) only raise rate limits / enrich metadata. See
[configuration.md](configuration.md).

### Does litkit-dsh download paywalled PDFs?

It tries open-access first, then institutional access (your university
credentials), then optional fallbacks. See the README **Legal notice** — use it
responsibly and only with access you are entitled to.

### Why did `litkit-dsh verify` fail?

Reference extraction needs **GROBID** (for PDFs) or **anystyle** (for .docx).
Both are optional but must be installed when you run verification:

- GROBID: `docker run -p 8070:8070 lfoppiano/grobid`
- anystyle: `gem install anystyle`

litkit-dsh now raises a clear error naming the missing tool instead of silently
reporting "0 references".

### What is the package name?

The PyPI distribution is **`litkit-search`** (because `litkit-dsh` was taken). The
import name and the CLI are still `litkit-dsh`.

### Can my agent (Claude / Codex / Cursor / DSH) use litkit-dsh?

Yes — via the MCP server (`litkit-mcp`). See [mcp.md](mcp.md). DeepSeek
Harness users can also install the dedicated plugin adapter — see
[dsh-plugin.md](dsh-plugin.md).

### zh-search does nothing / errors?

`zh-search` needs institutional library access (e.g. SZU). Configure
`INSTITUTIONAL_PROXY` / `INSTITUTIONAL_DIRECT` / `INSTITUTIONAL_COOKIE_FILE` in
`.env`. See [configuration.md](configuration.md).

### Export says "not yet implemented"?

Format conversion for `litkit-dsh export` is on the Roadmap; `search --export
ris|bibtex|json` already writes files.
