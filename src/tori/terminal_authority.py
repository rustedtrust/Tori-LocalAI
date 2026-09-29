"""Direct-peer and origin authority for the local browser terminal."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass

from .request_origin import RequestOrigin, RequestOriginKind


def is_terminal_local_peer(client_address: object) -> bool:
    """Use the socket peer, never Host, Origin, or forwarding headers."""
    if (not isinstance(client_address, tuple) or len(client_address) < 2
            or not isinstance(client_address[0], str)):
        return False
    try:
        address = ipaddress.ip_address(client_address[0])
    except ValueError:
        return False
    return address == ipaddress.ip_address("127.0.0.1") or address == ipaddress.ip_address("::1")


_ISSUER = object()


@dataclass(frozen=True, slots=True)
class TerminalLocalAuthority:
    """Evidence minted by a trusted direct local-web request boundary.

    This is an application capability, not a claim supplied in a request body.
    Callers must use the socket peer and the verified application origin.
    """

    browser_owner: str
    _issuer: object

    @classmethod
    def from_local_web(cls, *, browser_owner: str, client_address: object,
                       origin: RequestOrigin) -> TerminalLocalAuthority:
        if (not isinstance(origin, RequestOrigin)
                or origin.kind is not RequestOriginKind.LOCAL_WEB
                or not is_terminal_local_peer(client_address)
                or not isinstance(browser_owner, str)
                or len(browser_owner) < 32):
            raise PermissionError("Terminal authority requires a direct local browser session.")
        return cls(browser_owner, _ISSUER)

    def permits(self, browser_owner: str) -> bool:
        return self._issuer is _ISSUER and self.browser_owner == browser_owner
