"""PubMed search source via NCBI E-utilities.

Docs: https://www.ncbi.nlm.nih.gov/books/NBK25501/
Rate limit: 10 req/s (with API key), 3 req/s without.
"""

from __future__ import annotations

import re
from typing import Any
from xml.etree import ElementTree

import httpx

from litkit.core.models import Author, Paper, SearchResult, Venue
from litkit.sources import register
from litkit.sources.base import SearchSource


@register
class PubMed(SearchSource):
    name = "pubmed"
    rate_limit_key = "pubmed"

    def __init__(self, config: Any, client: httpx.AsyncClient | None = None):
        super().__init__(config, client)
        self._base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
        self._email = config.pubmed_email or config.crossref_email or "litkit@example.com"
        self._api_key = config.pubmed_key

    async def search(self, query: str, limit: int = 20, **kwargs: Any) -> SearchResult:
        # Step 1: esearch to get matching PMIDs
        count, pmids = await self._esearch(query, limit)
        if not pmids:
            return SearchResult(papers=(), total_estimated=0, source=self.name)

        # Step 2: esummary to get paper details
        summaries = await self._esummary(pmids)

        papers = [self._parse(uid, summaries[uid]) for uid in pmids if uid in summaries]
        return SearchResult(
            papers=tuple(papers),
            total_estimated=count,
            source=self.name,
        )

    async def fetch_by_doi(self, doi: str) -> Paper | None:
        doi_clean = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")
        _, pmids = await self._esearch(f"{doi_clean}[doi]", limit=10)
        if not pmids:
            return None
        summaries = await self._esummary(pmids[:1])
        if not summaries:
            return None
        uid = pmids[0]
        summary = summaries.get(uid, {})
        if not summary:
            return None
        return self._parse(uid, summary)

    async def _esearch(self, term: str, limit: int = 20) -> tuple[int, list[str]]:
        """Run E-utilities esearch and return (count, list of PMIDs).

        The E-utilities esearch endpoint is POSTed form data; the response
        is XML. Count and IdList are extracted from the parsed tree.
        """
        params: dict[str, str] = {
            "db": "pubmed",
            "term": term,
            "retmax": str(min(limit, 10000)),
            "email": self._email,
        }
        if self._api_key:
            params["api_key"] = self._api_key

        resp = await self._rate_limited(self._client.post(f"{self._base}esearch.fcgi", data=params))
        resp.raise_for_status()
        root = ElementTree.fromstring(resp.text)

        count_el = root.find(".//Count")
        count = int(count_el.text) if count_el is not None else 0

        id_els = root.findall(".//Id")
        pmids = [el.text for el in id_els if el.text]
        return count, pmids

    async def _esummary(self, pmids: list[str]) -> dict[str, Any]:
        """Run E-utilities esummary and return a dict of {uid: summary}.

        The esummary response is JSON (retmode=json), keyed by UID.
        """
        params: dict[str, str] = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "email": self._email,
            "retmode": "json",
        }
        if self._api_key:
            params["api_key"] = self._api_key

        resp = await self._rate_limited(
            self._client.post(f"{self._base}esummary.fcgi", data=params)
        )
        resp.raise_for_status()
        data = resp.json()
        result = data.get("result", {})
        uids = result.get("uids", [])
        return {uid: result.get(uid, {}) for uid in uids}

    def _parse(self, pmid: str, summary: dict[str, Any]) -> Paper:
        title = summary.get("title", "")

        # DOI and PMC ID from articleids array
        doi = ""
        pmcid = ""
        article_ids = summary.get("articleids") or []
        for aid in article_ids:
            aid_type = aid.get("idtype", "")
            aid_value = aid.get("value", "")
            if aid_type == "doi":
                doi = aid_value.replace("https://doi.org/", "")
            elif aid_type == "pmc":
                pmcid = aid_value

        # Authors â€” PubMed esummary returns {name: "Doe J"} format
        authors_data = summary.get("authors") or []
        authors = tuple(
            Author(
                given=self._parse_given_name(au.get("name", "")),
                family=self._parse_family_name(au.get("name", "")),
            )
            for au in authors_data
            if au.get("name")
        )

        # Journal / venue
        source = summary.get("source", "")
        issn = summary.get("issn", "")
        venue = Venue(
            name=source,
            issn=issn,
            type="journal",
        )

        # Year from pubdate
        pubdate = summary.get("pubdate", "")
        year = 0
        if pubdate:
            m = re.match(r"(\d{4})", pubdate)
            if m:
                year = int(m.group(1))

        # Bibliographic details
        volume = summary.get("volume", "")
        issue = summary.get("issue", "")
        pages = summary.get("pages", "")
        if not pages:
            eloc = summary.get("elocationid", "")
            if eloc:
                pages = eloc

        # Abstract
        abstract = summary.get("abstract", "")

        # Keywords
        keywords = tuple(summary.get("keywords") or [])

        # Subjects from MeSH terms
        mesh_terms = summary.get("meshterms") or []
        subjects = tuple(mesh_terms)

        return Paper(
            doi=doi,
            title=title,
            authors=authors,
            venue=venue,
            year=year,
            volume=volume,
            issue=issue,
            pages=pages,
            abstract=abstract,
            keywords=keywords,
            source_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            source=self.name,
            subjects=subjects,
            extra={
                "pmid": pmid,
                "pmcid": pmcid,
            },
        )

    @staticmethod
    def _parse_given_name(name: str) -> str:
        """Extract given name from PubMed author name string.

        PubMed formats include "Doe J" and "Doe, John".
        """
        if not name:
            return ""
        if "," in name:
            return name.split(",", 1)[1].strip()
        parts = name.strip().split()
        return " ".join(parts[1:]) if len(parts) > 1 else ""

    @staticmethod
    def _parse_family_name(name: str) -> str:
        """Extract family name from PubMed author name string."""
        if not name:
            return ""
        if "," in name:
            return name.split(",", 1)[0].strip()
        parts = name.strip().split()
        return parts[0] if parts else ""
