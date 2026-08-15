# CLI Reference

```bash
litkit <command> [options]
```

## Commands

### `litkit search` — multi-source search

```bash
litkit search "deep learning drug discovery"                 # all sources, 20/source
litkit search "RAG" -s arxiv,pubmed -l 10                    # specific sources
litkit search "graph neural networks" --year-from 2023       # year filter
litkit search "LLM agents" --export ris -o refs.ris          # export (ris|bibtex|json)
```

### `litkit download` — search + download PDFs

```bash
litkit download "10.1038/nature14539"          # by DOI
litkit download "retrieval augmented generation" -l 5
```

### `litkit download-suppl` — supplementary materials

```bash
litkit download-suppl <DOI>
```

### `litkit verify` — citation audit on a manuscript

```bash
litkit verify paper.docx -o report/
litkit verify paper.pdf -o report/        # requires GROBID or anystyle (see troubleshooting.md)
```

### `litkit workflow` — built-in workflows

```bash
litkit workflow citation-audit --manuscript paper.docx --output report/
litkit workflow bulk-review --query "LLM reasoning" --download --export ris
```

### `litkit topic-search` / `deep-search` — research expansion

```bash
litkit topic-search "How do multi-agent LLM systems coordinate?"
litkit deep-search "Economic impact of AI on software engineering"
```

### `litkit zh-search` — Chinese literature (needs institutional access)

```bash
litkit zh-search "检索增强生成"
```

### `litkit sources` — list the 25 sources

```bash
litkit sources
```

### `litkit export` — export results

> ⚠️ Format conversion is **in progress** (Roadmap). RIS/BibTeX/JSON export from
> `search --export` currently writes the corresponding file.

```bash
litkit search "LLM agents" --export ris -o refs.ris
```

### `litkit sync-keys` — configure API keys

```bash
litkit sync-keys path/to/keys.txt
```

### `litkit doctor` — environment self-check

```bash
litkit doctor
```

## Global behavior

- Output is a rich table on TTY; pipe-friendly tools should use the MCP server
  or `--json` (available on search/sources/verify/download/topic-search).
- On legacy Windows consoles, output is re-encoded with `errors="replace"` so
  Greek letters / CJK in paper titles never crash the CLI.
