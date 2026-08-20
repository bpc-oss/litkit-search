# CLI Reference

```bash
litkit-dsh <command> [options]
```

## Commands

### `litkit-dsh search` — multi-source search

```bash
litkit-dsh search "deep learning drug discovery"                 # all sources, 20/source
litkit-dsh search "RAG" -s arxiv,pubmed -l 10                    # specific sources
litkit-dsh search "graph neural networks" --year-from 2023       # year filter
litkit-dsh search "LLM agents" --export ris -o refs.ris          # export (ris|bibtex|json)
```

### `litkit-dsh download` — search + download PDFs

```bash
litkit-dsh download "10.1038/nature14539"          # by DOI
litkit-dsh download "retrieval augmented generation" -l 5
```

### `litkit-dsh download-suppl` — supplementary materials

```bash
litkit-dsh download-suppl <DOI>
```

### `litkit-dsh verify` — citation audit on a manuscript

```bash
litkit-dsh verify paper.docx -o report/
litkit-dsh verify paper.pdf -o report/        # requires GROBID or anystyle (see troubleshooting.md)
```

### `litkit-dsh workflow` — built-in workflows

```bash
litkit-dsh workflow citation-audit --manuscript paper.docx --output report/
litkit-dsh workflow bulk-review --query "LLM reasoning" --download --export ris
```

### `litkit-dsh topic-search` / `deep-search` — research expansion

```bash
litkit-dsh topic-search "How do multi-agent LLM systems coordinate?"
litkit-dsh deep-search "Economic impact of AI on software engineering"
```

### `litkit-dsh zh-search` — Chinese literature (needs institutional access)

```bash
litkit-dsh zh-search "检索增强生成"
```

### `litkit-dsh sources` — list the 25 sources

```bash
litkit-dsh sources
```

### `litkit-dsh export` — export results

> ⚠️ Format conversion is **in progress** (Roadmap). RIS/BibTeX/JSON export from
> `search --export` currently writes the corresponding file.

```bash
litkit-dsh search "LLM agents" --export ris -o refs.ris
```

### `litkit-dsh sync-keys` — configure API keys

```bash
litkit-dsh sync-keys path/to/keys.txt
```

### `litkit-dsh doctor` — environment self-check

```bash
litkit-dsh doctor
```

## Global behavior

- Output is a rich table on TTY; pipe-friendly tools should use the MCP server
  or `--json` (available on search/sources/verify/download/topic-search).
- On legacy Windows consoles, output is re-encoded with `errors="replace"` so
  Greek letters / CJK in paper titles never crash the CLI.
