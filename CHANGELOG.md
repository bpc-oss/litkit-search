# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-08

### Added
- Initial open-source release of `litkit` (distributed as `litkit-search` on
  GitHub; PyPI publishing planned).
- Multi-source academic literature search across 25 sources (arXiv, PubMed,
  Crossref, Semantic Scholar, OpenAlex, DBLP, IEEE Xplore, Scopus, WoS, SSRN,
  bioRxiv, Zenodo, DOAJ, Scite, OpenCitations, and more) — zero API keys required
  for most sources.
- Bulk retrieval with deduplication and ranked results.
- Citation audit (`litkit verify`) for manuscripts (docx/pdf).
- PDF download chain with multi-strategy fallbacks (open access, institutional,
  browser-assisted).
- Export to BibTeX / RIS / JSON.
- Workflows: `topic-search`, `deep-search`, `bulk-review`.
- Chinese literature search (`zh-search`).

### Security notes
- Shadow-library and institutional-access download paths are included as
  declared functionality. See README "Legal notice" before use.
