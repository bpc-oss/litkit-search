# litkit-dsh skill — academic literature search for DSH

Use the `litkit_*` tools when the task involves:

- **Scholarly literature search** — finding papers, DOIs, citations across
  arXiv / PubMed / Crossref / Semantic Scholar / OpenAlex / DBLP / IEEE /
  Scopus / WoS / SSRN and more (25+ sources).
- **Literature review / related work** — bulk retrieval with deduplication.
- **Citation verification** — checking a manuscript's references
  (`litkit_verify`, needs anystyle/GROBID).
- **PDF acquisition** — `litkit_download` (open-access first, then
  institutional/shadow fallbacks — respect access entitlements).

## When NOT to use

- General web questions without a scholarly angle → use web search tools.
- The query needs current news, pricing, or non-academic sources.

## Workflow hints

1. Prefer `litkit_search` over generic search for academic queries; pass
   `sources` to narrow (e.g. `arxiv,pubmed`) and `year_from/year_to` to bound.
2. Use `litkit_sources` first when unsure which sources are available.
3. If tools report a CLI error, run `litkit_doctor` — it checks Python,
   dependencies, source registry, network, and optional tools.
4. `litkit_verify` needs `anystyle` (gem) or GROBID (docker) installed; the
   error message explains how.
