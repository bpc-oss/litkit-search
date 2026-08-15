"""DNS-over-HTTPS resolution for shadow library domains.

GFW poisons system DNS for Sci-Hub, LibGen, and Anna's Archive domains,
returning sinkhole IPs (198.18.x.x). This module patches
``socket.getaddrinfo`` to bypass poisoning by resolving these domains
via DoH providers accessible from China.
"""

from __future__ import annotations

import concurrent.futures
import logging
import socket

logger = logging.getLogger(__name__)

# Sinkhole prefixes used by GFW DNS poisoning (IPv4 + IPv6).
_SINKHOLE_PREFIX = "198.18."
_SINKHOLE_V6_PREFIX = "fdfe:dcba:9876::"

# Shadow library domains to intercept via the socket patch.
_SHADOW_DOMAINS = frozenset(
    {
        # Sci-Hub
        "sci-hub.se",
        "sci-hub.sg",
        "sci-hub.ru",
        "sci-hub.st",
        "sci-hub.ee",
        "sci-hub.shop",
        "sci-hub.ren",
        "sci-hub.box",
        # Sci-Hub PDF CDN
        "sci.bban.top",
        # LibGen (new mirrors reachable from China)
        "libgen.is",
        "libgen.rs",
        "libgen.st",
        "libgen.li",
        "libgen.fun",
        "libgen.gl",
        "libgen.vg",
        "libgen.la",
        "libgen.bz",
        # LibGen CDN
        "booksdl.lc",
        # Anna's Archive
        "annas-archive.org",
        "annas-archive.se",
        "annas-archive.gs",
    }
)

# Wildcard suffix matching for CDN subdomains.
# Any host ending with the suffix uses the resolved IP of its base domain.
# Format: (suffix, base_domain)
_SHADOW_WILDCARDS: list[tuple[str, str]] = [
    (".booksdl.lc", "booksdl.lc"),
]

# DoH providers usable from China (ordered — first success wins).
# alidns serves the Google-style JSON API at /resolve; doh.pub and
# cloudflare-dns.com use the same JSON query format at /dns-query.
_DOH_PROVIDERS = [
    "https://dns.alidns.com/resolve",
    "https://doh.pub/dns-query",
    "https://cloudflare-dns.com/dns-query",
]

# Resolved IPs: domain -> [ip, ...]
_resolved: dict[str, list[str]] = {}

# Preserve original before any patching.
_original_getaddrinfo = socket.getaddrinfo


def _resolve_via_doh(domain: str) -> list[str] | None:
    """Resolve *domain* via DoH, return A-record IPs or None.

    Uses ``httpx`` with a strict 4-second timeout instead of ``urllib``,
    because ``urllib.request.urlopen`` timeout on Windows does not
    reliably abort hung SSL/TLS handshakes.
    """
    try:
        import httpx
    except ImportError:
        return None

    for provider in _DOH_PROVIDERS:
        url = f"{provider}?name={domain}&type=A"
        try:
            resp = httpx.get(
                url,
                headers={"Accept": "application/dns-json"},
                timeout=httpx.Timeout(4.0, connect=3.0),
            )
            data = resp.json()
            ips = [
                a["data"]
                for a in data.get("Answer", [])
                if a.get("type") == 1
                and not a["data"].startswith(_SINKHOLE_PREFIX)
                and not a["data"].startswith(_SINKHOLE_V6_PREFIX)
            ]
            if ips:
                logger.debug("DoH %s -> %s via %s", domain, ips, provider)
                return ips
        except (httpx.HTTPError, OSError, ValueError) as exc:
            logger.debug("DoH %s failed via %s: %s", domain, provider, exc)
            continue
    logger.warning("DoH resolution failed for %s (all providers)", domain)
    return None


def _patched_getaddrinfo(
    host: str | bytes | None,
    port: int | str | None,
    family: int = 0,
    socktype: int = 0,
    proto: int = 0,
    flags: int = 0,
) -> list[tuple]:
    """Override ``socket.getaddrinfo`` for shadow library domains.

    Non-shadow-lib domains fall through to the system resolver.
    Also supports wildcard CDN subdomains (e.g. cdn4.booksdl.lc).
    """
    # socket.getaddrinfo can receive host as bytes; normalize to str.
    if isinstance(host, bytes):
        host = host.decode("ascii")

    port_num = int(port) if port is not None else 80

    # Exact match in resolved domains — prefer an IPv4 address because the
    # returned tuple is AF_INET (GFW also poisons IPv6 AAAA answers).
    if host in _resolved:
        for ip in _resolved[host]:
            if ":" not in ip:
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port_num))]
        if _resolved[host]:
            return [
                (
                    socket.AF_INET6,
                    socket.SOCK_STREAM,
                    6,
                    "",
                    (_resolved[host][0], port_num, 0, 0),
                )
            ]

    # Wildcard CDN match (e.g. cdn4.booksdl.lc → booksdl.lc IP).
    for suffix, base in _SHADOW_WILDCARDS:
        if host and host.endswith(suffix) and base in _resolved and _resolved[base]:
            for ip in _resolved[base]:
                if ":" not in ip:
                    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port_num))]
            return [
                (
                    socket.AF_INET6,
                    socket.SOCK_STREAM,
                    6,
                    "",
                    (_resolved[base][0], port_num, 0, 0),
                )
            ]

    return _original_getaddrinfo(host, port, family, socktype, proto, flags)


def _resolve_one_domain(domain: str) -> None:
    """Resolve a single shadow-library domain — system DNS first, DoH fallback."""
    # Check whether the system DNS already returns a real IP.
    try:
        addrs = _original_getaddrinfo(domain, 80)
        good = [
            a
            for a in addrs
            if not a[4][0].startswith(_SINKHOLE_PREFIX)
            and not a[4][0].startswith(_SINKHOLE_V6_PREFIX)
        ]
        if good:
            ip = good[0][4][0]
            logger.debug("System DNS OK for %s -> %s (skipping DoH)", domain, ip)
            _resolved.setdefault(domain, []).append(ip)
            return
    except (OSError, socket.gaierror):
        pass

    # System DNS poisoned — resolve via DoH.
    ips = _resolve_via_doh(domain)
    if ips:
        _resolved[domain] = ips
        logger.info("DoH resolved %s -> %s", domain, ips)
    else:
        logger.warning("Cannot resolve %s (all DNS failed)", domain)


def ensure_resolved() -> None:
    """Ensure all shadow library domains are resolved via DoH.

    Patches ``socket.getaddrinfo`` on first call.  Idempotent — no-op on
    subsequent calls.

    Domains are resolved **in parallel** (up to 5 threads) with a total
    ceiling of 20 seconds so the caller never blocks indefinitely, even
    when some domains are unreachable from China.
    """
    if _resolved:
        return

    # Apply the patch right away so non-shadow resolutions still work.
    socket.getaddrinfo = _patched_getaddrinfo

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=5)
    futures = {pool.submit(_resolve_one_domain, d): d for d in sorted(_SHADOW_DOMAINS)}
    concurrent.futures.wait(futures.keys(), timeout=20)
    for f in futures:
        if not f.done():
            logger.debug("DNS resolution timed out for %s", futures[f])
    pool.shutdown(wait=False)  # Don't block on stragglers
