"""Shared bounded endpoint policy for Tori-owned local HTTP integrations."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit


_APPROVED_LOCAL_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)


def is_valid_local_http_endpoint(endpoint: str) -> bool:
    """Accept one explicit numeric loopback/RFC1918 HTTP API root."""

    if not isinstance(endpoint, str):
        return False
    try:
        parsed = urlsplit(endpoint)
        address = ipaddress.ip_address(parsed.hostname or "")
        port = parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme == "http"
        and isinstance(address, ipaddress.IPv4Address)
        and any(address in network for network in _APPROVED_LOCAL_NETWORKS)
        and port is not None
        and 1 <= port <= 65535
        and parsed.username is None
        and parsed.password is None
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
    )


__all__ = ["is_valid_local_http_endpoint"]
