"""Tests for litkit.doctor — environment self-check."""

from __future__ import annotations

import sys

from litkit.doctor import CheckResult, run_checks


def test_run_checks_returns_ordered_nonempty_results():
    results = run_checks()
    assert isinstance(results, list)
    assert len(results) >= 8
    assert all(isinstance(r, CheckResult) for r in results)
    assert all(r.status in ("PASS", "FAIL", "WARN") for r in results)
    assert all(r.name and r.detail for r in results)


def test_python_check_passes_on_current_interpreter():
    results = {r.name: r for r in run_checks()}
    py = results["python"]
    # The test suite itself requires Python 3.11+, so this must PASS.
    assert py.status == "PASS"


def test_sources_registry_check_ok():
    results = {r.name: r for r in run_checks()}
    sources = results["sources registry"]
    assert sources.status in ("PASS", "WARN")
    assert "sources registered" in sources.detail


def test_network_check_never_raises_and_never_fails():
    results = {r.name: r for r in run_checks()}
    network = results["network"]
    # Offline environments must degrade to WARN, never FAIL or crash.
    assert network.status in ("PASS", "WARN")


def test_env_to_attr_mapping():
    from litkit.doctor import _env_to_attr

    assert _env_to_attr("SCOPUS_API_KEY") == "scopus_key"
    assert _env_to_attr("SEMANTIC_SCHOLAR_API_KEY") == "semantic_scholar_key"
    assert _env_to_attr("PUBMED_API_KEY") == "pubmed_key"
