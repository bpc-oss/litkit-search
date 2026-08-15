"""Search source plugins — one file per source, all registered here."""

# ruff: noqa: I001

from typing import Any

_registry: dict[str, type[Any]] = {}


def register(source_cls: type[Any]) -> type[Any]:
    _registry[source_cls.name] = source_cls
    return source_cls


def get(name: str) -> type[Any] | None:
    if name in _registry:
        return _registry[name]
    raise KeyError(f"Unknown source: {name}. Available: {list(_registry)}")


def all_sources() -> dict[str, type[Any]]:
    return dict(_registry)


# Import and register all sources
from litkit.sources import acm  # noqa: E402, F401
from litkit.sources import arxiv  # noqa: E402, F401
from litkit.sources import base_search  # noqa: E402, F401
from litkit.sources import biorxiv  # noqa: E402, F401
from litkit.sources import chemrxiv  # noqa: E402, F401
from litkit.sources import core as core_source  # noqa: E402, F401
from litkit.sources import crossref  # noqa: E402, F401
from litkit.sources import dblp  # noqa: E402, F401
from litkit.sources import dimensions  # noqa: E402, F401
from litkit.sources import doaj  # noqa: E402, F401
from litkit.sources import doi_resolver  # noqa: E402, F401
from litkit.sources import ieee_xplore  # noqa: E402, F401
from litkit.sources import lens  # noqa: E402, F401
from litkit.sources import openalex  # noqa: E402, F401
from litkit.sources import opencitations  # noqa: E402, F401
from litkit.sources import orcid  # noqa: E402, F401
from litkit.sources import pubmed  # noqa: E402, F401
from litkit.sources import scite  # noqa: E402, F401
from litkit.sources import scopus  # noqa: E402, F401
from litkit.sources import semantic_scholar  # noqa: E402, F401
from litkit.sources import springer  # noqa: E402, F401
from litkit.sources import ssrn  # noqa: E402, F401
from litkit.sources import szu_library  # noqa: E402, F401
from litkit.sources import wos  # noqa: E402, F401
from litkit.sources import zenodo  # noqa: E402, F401
