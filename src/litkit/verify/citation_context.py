"""Citation context analysis — verifying whether references support claims.

Uses Semantic Scholar citation contexts API.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from litkit.config import EnvConfig, load_env


@dataclass
class CitationContext:
    citing_paper_id: str = ""
    cited_paper_id: str = ""
    context: str = ""
    is_influential: bool | None = None
    intent: str = ""


class CitationContextAnalyzer:
    """Analyze citation contexts using Semantic Scholar API."""

    def __init__(self, config: EnvConfig | None = None):
        self._config = config or load_env()
        self._client = httpx.AsyncClient(timeout=15.0)
        self._base = "https://api.semanticscholar.org/graph/v1"

    async def get_contexts(self, citing_doi: str, cited_doi: str) -> list[CitationContext]:
        """Get citation context for one specific cited paper."""
        resp = await self._client.get(
            f"{self._base}/paper/DOI:{citing_doi}/citations",
            params={"fields": "context,intents,isInfluential", "limit": 50},
        )
        if resp.status_code != 200:
            return []

        data = resp.json()
        contexts = []
        for entry in data.get("data", []):
            citing = entry.get("citingPaper", {}) or {}
            citing_doi_val = (citing.get("externalIds") or {}).get("DOI", "") or ""
            if cited_doi.lower() in citing_doi_val.lower():
                contexts.append(
                    CitationContext(
                        citing_paper_id=citing_doi,
                        cited_paper_id=cited_doi,
                        context=(entry.get("context") or ""),
                        is_influential=entry.get("isInfluential"),
                        intent="|".join(entry.get("intents", [])),
                    )
                )
        return contexts

    async def get_all_citations(self, doi: str) -> list[CitationContext]:
        """Get all citation contexts for a paper."""
        resp = await self._client.get(
            f"{self._base}/paper/DOI:{doi}/citations",
            params={"fields": "context,intents,isInfluential", "limit": 100},
        )
        if resp.status_code != 200:
            return []

        data = resp.json()
        return [
            CitationContext(
                citing_paper_id=(c.get("citingPaper", {}) or {}).get("paperId", ""),
                cited_paper_id=doi,
                context=(c.get("context") or ""),
                is_influential=c.get("isInfluential"),
                intent="|".join(c.get("intents", [])),
            )
            for c in data.get("data", [])
        ]

    def classify_support(self, context: str) -> bool | None:
        """Classify whether a citation context indicates supporting or
        contrasting evidence."""
        ctx = context.lower()
        supporting = {
            "we confirm",
            "consistent with",
            "in agreement with",
            "as previously shown",
            "as demonstrated by",
            "support",
            "similar to",
            "comparable to",
        }
        contrasting = {
            "however",
            "in contrast",
            "contradicts",
            "disagree",
            "inconsistent",
            "contrary to",
            "but",
            "although",
            "nevertheless",
            "on the other hand",
        }
        has_supporting = any(p in ctx for p in supporting)
        has_contrasting = any(p in ctx for p in contrasting)
        if has_supporting and not has_contrasting:
            return True
        if has_contrasting and not has_supporting:
            return False
        return None

    async def close(self) -> None:
        await self._client.aclose()
