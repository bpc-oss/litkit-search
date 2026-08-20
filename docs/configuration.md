# Configuration

## Zero-key out of the box

The following sources work immediately with **no API keys**: arXiv, PubMed,
Crossref, Semantic Scholar, OpenAlex, DBLP, DOAJ, Zenodo, bioRxiv, ChemRxiv,
SSRN, Scite, OpenCitations, ACM, BASE, CORE, Dimensions, Lens, Springer, ORCID,
and more (25 sources total — `litkit-dsh sources` lists them with their key
requirement).

## Optional API keys

Keys unlock higher rate limits / richer metadata. Configure them either way:

### Interactive

```bash
litkit-dsh sync-keys            # point it at a text file with KEY=VALUE lines
```

### Manual (.env)

```bash
cp .env.example .env        # Windows PowerShell: Copy-Item .env.example .env
```

Then edit `.env`:

| Variable | Purpose |
|---|---|
| `SCOPUS_API_KEY` | Scopus (commercial) |
| `WOS_API_KEY` | Web of Science (commercial) |
| `OPENALEX_API_KEY` | OpenAlex (higher limits) |
| `SEMANTIC_SCHOLAR_API_KEY` | Semantic Scholar (higher limits) |
| `PUBMED_EMAIL` / `PUBMED_API_KEY` | PubMed/Entrez (email recommended) |
| `IEEE_API_KEY` / `ACM_API_KEY` / `SPRINGER_API_KEY` | Publisher APIs |
| `SCITE_API_KEY` / `DIMENSIONS_API_KEY` | Scite / Dimensions |
| `CROSSREF_EMAIL` / `UNPAYWALL_EMAIL` / `CITATION_VERIFIER_EMAIL` | Polite-pool emails (use yours) |

## Institutional access (publisher PDFs)

For paywalled publisher PDFs your institution subscribes to:

| Variable | Purpose |
|---|---|
| `INSTITUTIONAL_PROXY` | EZProxy prefix, e.g. `https://ezproxy.youruni.edu/login?url=` |
| `INSTITUTIONAL_DIRECT` | `true` when on campus / VPN (no proxy prefix) |
| `INSTITUTIONAL_COOKIE_FILE` | Path to a cookie file exported from your browser after logging in |

> Only use access you are entitled to. See the README **Legal notice**.

## Chinese literature (zh-search)

`litkit-dsh zh-search` targets Chinese academic sources and requires institutional
library access (e.g. SZU library). Configure the same institutional variables
above. Without institutional access the command will report what is missing.

## Interpreting `litkit-dsh doctor`

| Status | Meaning |
|---|---|
| PASS | Everything needed for that check is present |
| WARN | Advisory — feature degrades but core search works (e.g. no optional keys, no anystyle) |
| FAIL | Core functionality broken — fix before use (exit code 1) |
