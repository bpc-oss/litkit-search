"""Tests for the shadow-library DNS-over-HTTPS resolver (_dns)."""

from __future__ import annotations

import socket

import pytest

from litkit.downloaders import _dns


def test_patched_getaddrinfo_uses_resolved_ipv4(monkeypatch):
    """Resolved domains return a working AF_INET tuple."""
    monkeypatch.setattr(_dns, "_resolved", {"sci-hub.ru": ["190.115.31.218"]})
    addrs = _dns._patched_getaddrinfo("sci-hub.ru", 80)
    assert addrs == [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("190.115.31.218", 80))
    ]


def test_patched_getaddrinfo_prefers_ipv4_over_v6(monkeypatch):
    """When both IPv4 and IPv6 are cached, the AF_INET tuple wins."""
    monkeypatch.setattr(
        _dns, "_resolved", {"libgen.gl": ["172.67.139.134", "fdfe:dcba:9876::99"]}
    )
    addrs = _dns._patched_getaddrinfo("libgen.gl", 80)
    assert addrs[0][0] == socket.AF_INET
    assert addrs[0][4][0] == "172.67.139.134"


def test_patched_getaddrinfo_v6_only_returns_af_inet6(monkeypatch):
    """If only IPv6 is cached, return an AF_INET6 tuple (no crash)."""
    monkeypatch.setattr(_dns, "_resolved", {"annas-archive.se": ["2a01:4f8::1"]})
    addrs = _dns._patched_getaddrinfo("annas-archive.se", 443)
    assert addrs[0][0] == socket.AF_INET6
    assert addrs[0][4][0] == "2a01:4f8::1"


def test_patched_getaddrinfo_wildcard_cdn(monkeypatch):
    """Wildcard CDN subdomains resolve against their base domain."""
    monkeypatch.setattr(_dns, "_resolved", {"booksdl.lc": ["104.21.43.49"]})
    addrs = _dns._patched_getaddrinfo("cdn4.booksdl.lc", 80)
    assert addrs == [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("104.21.43.49", 80))
    ]


def test_patched_getaddrinfo_falls_through_for_unknown(monkeypatch):
    """Non-shadow domains fall through to the original resolver."""
    monkeypatch.setattr(_dns, "_resolved", {"sci-hub.ru": ["190.115.31.218"]})

    def fake_orig(*a, **kw):
        raise socket.gaierror("no address")

    monkeypatch.setattr(_dns, "_original_getaddrinfo", fake_orig)
    with pytest.raises(socket.gaierror):
        _dns._patched_getaddrinfo("definitely-not-a-real-host.invalid", 80)


def test_resolve_one_domain_skips_v6_sinkhole(monkeypatch):
    """System DNS returning the fdfe:dcba:9876:: sinkhole triggers DoH."""
    sinkhole = [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("fdfe:dcba:9876::a4", 80, 0, 0))]

    def fake_getaddrinfo(host, port, *a, **kw):
        return sinkhole

    monkeypatch.setattr(_dns, "_original_getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(_dns, "_resolved", {})
    monkeypatch.setattr(
        _dns, "_resolve_via_doh", lambda domain: ["190.115.31.218"]
    )
    _dns._resolve_one_domain("sci-hub.ru")
    assert _dns._resolved["sci-hub.ru"] == ["190.115.31.218"]


def test_resolve_one_domain_skips_ipv4_sinkhole(monkeypatch):
    """System DNS returning the 198.18.x.x sinkhole triggers DoH."""
    sinkhole = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.18.0.168", 80))]

    def fake_getaddrinfo(host, port, *a, **kw):
        return sinkhole

    monkeypatch.setattr(_dns, "_original_getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(_dns, "_resolved", {})
    monkeypatch.setattr(_dns, "_resolve_via_doh", lambda domain: ["104.18.43.196"])
    _dns._resolve_one_domain("sci-hub.ee")
    assert _dns._resolved["sci-hub.ee"] == ["104.18.43.196"]


def test_resolve_via_doh_filters_sinkholes(monkeypatch):
    """DoH answers that are sinkholes are dropped, not cached."""
    import respx

    with respx.mock:
        respx.get(url__regex=r"doh\.pub.*").respond(
            200,
            headers={"content-type": "application/dns-json"},
            json={
                "Answer": [
                    {"type": 1, "data": "198.18.0.1"},
                    {"type": 1, "data": "fdfe:dcba:9876::1"},
                    {"type": 1, "data": "104.18.43.196"},
                ]
            },
        )
        # Only doh.pub answers in this test — force provider order.
        monkeypatch.setattr(
            _dns,
            "_DOH_PROVIDERS",
            ["https://doh.pub/dns-query"],
        )
        ips = _dns._resolve_via_doh("sci-hub.ee")
    assert ips == ["104.18.43.196"]
