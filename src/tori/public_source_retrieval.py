"""Bounded public HTTP/HTTPS source retrieval adapter."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urljoin, urlsplit, urlunsplit

from . import __version__
from .source_retrieval import (
    MAX_PUBLIC_URL_LENGTH,
    MAX_RETRIEVAL_SOURCES,
    RetrievedSource,
    SourceRetrievalError,
    SourceRetrievalFailure,
    SourceRetrievalPort,
    SourceRetrievalRequest,
    SourceRetrievalResult,
)


_SUPPORTED_TYPES = {
    "text/html",
    "application/xhtml+xml",
    "text/plain",
    "text/markdown",
    "text/x-markdown",
}
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


@dataclass(frozen=True, slots=True)
class ResolvedPublicURL:
    url: str
    hostname: str
    port: int
    addresses: tuple[str, ...]


HTTPTransport = Callable[
    [ResolvedPublicURL, float, int],
    tuple[int, Mapping[str, str], bytes],
]
Resolver = Callable[[str, int], Sequence[str]]


class PublicSourceRetriever(SourceRetrievalPort):
    """Retrieve a tiny allowlisted set of public text sources without crawling."""

    def __init__(
        self,
        *,
        transport: HTTPTransport | None = None,
        resolver: Resolver | None = None,
    ) -> None:
        self._transport = transport or _http_transport
        self._resolver = resolver or _resolve_addresses

    def retrieve(self, request: SourceRetrievalRequest) -> SourceRetrievalResult:
        if not request.targets:
            return SourceRetrievalResult((), ())
        if len(request.targets) > MAX_RETRIEVAL_SOURCES:
            raise SourceRetrievalError(
                "Too many sources were selected for one request.", code="too_many_sources"
            )
        successes: list[RetrievedSource] = []
        failures: list[SourceRetrievalFailure] = []
        remaining = request.maximum_total_characters
        for target in request.targets:
            if remaining <= 0:
                failures.append(SourceRetrievalFailure(
                    target.url, target.title, "evidence_limit"
                ))
                continue
            try:
                final_url, headers, body = self._fetch(
                    target.url,
                    timeout=request.timeout_seconds,
                    maximum=request.maximum_body_bytes,
                    redirects=request.maximum_redirects,
                )
                content_type = _content_type(headers)
                title, text = _extract_content(
                    body,
                    content_type,
                    maximum=min(request.maximum_text_characters, remaining),
                )
                successes.append(RetrievedSource(
                    target.url,
                    final_url,
                    title or target.title,
                    text,
                    content_type,
                    target.relationship,
                ))
                remaining -= len(text)
            except SourceRetrievalError as exc:
                failures.append(SourceRetrievalFailure(
                    target.url, target.title, exc.code
                ))
        return SourceRetrievalResult(tuple(successes), tuple(failures))

    def _fetch(
        self, url: str, *, timeout: float, maximum: int, redirects: int
    ) -> tuple[str, Mapping[str, str], bytes]:
        current = _strip_fragment(url)
        for redirect_number in range(redirects + 1):
            resolved = _validated_public_url(current, self._resolver)
            try:
                status, headers, body = self._transport(resolved, timeout, maximum)
            except SourceRetrievalError:
                raise
            except (
                OSError,
                TimeoutError,
                ssl.SSLError,
                http.client.HTTPException,
            ) as exc:
                raise SourceRetrievalError(
                    "The public source could not be reached.", code="unavailable"
                ) from exc
            if status in _REDIRECT_STATUSES:
                location = _header(headers, "location")
                if location is None or redirect_number == redirects:
                    raise SourceRetrievalError(
                        "The public source exceeded the redirect limit.",
                        code="redirect_limit",
                    )
                current = urljoin(current, location)
                continue
            if status != 200:
                raise SourceRetrievalError(
                    "The public source returned an unsuccessful response.",
                    code="http_error",
                )
            if len(body) > maximum:
                raise SourceRetrievalError(
                    "The public source response was too large.", code="response_too_large"
                )
            return current, headers, body
        raise AssertionError("redirect loop must terminate")


def _strip_fragment(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))


def _validated_public_url(url: str, resolver: Resolver) -> ResolvedPublicURL:
    if len(url) > MAX_PUBLIC_URL_LENGTH or any(
        ord(character) < 32 or ord(character) == 127 or character.isspace()
        for character in url
    ):
        raise SourceRetrievalError("The source URL is unsafe.", code="unsafe_url")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise SourceRetrievalError("The source URL is unsafe.", code="unsafe_url") from exc
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or "\\" in url
    ):
        raise SourceRetrievalError("The source URL is unsafe.", code="unsafe_url")
    try:
        hostname = (
            parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
        )
    except UnicodeError as exc:
        raise SourceRetrievalError(
            "The source URL is unsafe.", code="unsafe_url"
        ) from exc
    if not hostname or hostname == "localhost" or hostname.endswith(".localhost"):
        raise SourceRetrievalError(
            "The source destination is not public.", code="unsafe_destination"
        )
    effective_port = port or (443 if parsed.scheme.lower() == "https" else 80)
    try:
        addresses = tuple(dict.fromkeys(resolver(hostname, effective_port)))
    except (OSError, UnicodeError) as exc:
        raise SourceRetrievalError(
            "The public source host could not be resolved.", code="unavailable"
        ) from exc
    if not addresses:
        raise SourceRetrievalError(
            "The public source host could not be resolved.", code="unavailable"
        )
    try:
        parsed_addresses = tuple(ipaddress.ip_address(address) for address in addresses)
    except ValueError as exc:
        raise SourceRetrievalError(
            "The source destination is ambiguous.", code="unsafe_destination"
        ) from exc
    if any(
        not address.is_global
        or address.is_multicast
        or address.is_unspecified
        or address.is_loopback
        or address.is_link_local
        or address.is_private
        or address.is_reserved
        for address in parsed_addresses
    ):
        raise SourceRetrievalError(
            "The source destination is not public.", code="unsafe_destination"
        )
    return ResolvedPublicURL(url, hostname, effective_port, addresses)


def _resolve_addresses(hostname: str, port: int) -> tuple[str, ...]:
    return tuple(dict.fromkeys(
        item[4][0]
        for item in socket.getaddrinfo(
            hostname, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
        )
    ))


def _http_transport(
    target: ResolvedPublicURL, timeout: float, maximum: int
) -> tuple[int, Mapping[str, str], bytes]:
    parsed = urlsplit(target.url)
    connection_class = _PinnedHTTPSConnection if parsed.scheme == "https" else _PinnedHTTPConnection
    connection = connection_class(
        target.hostname,
        target.port,
        target.addresses[0],
        timeout=timeout,
    )
    path = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    host_header = target.hostname
    if ":" in host_header:
        host_header = f"[{host_header}]"
    default_port = 443 if parsed.scheme == "https" else 80
    if target.port != default_port:
        host_header = f"{host_header}:{target.port}"
    try:
        connection.request(
            "GET",
            path,
            headers={
                "Accept": "text/html,text/plain,text/markdown;q=0.9",
                "Accept-Encoding": "identity",
                "Host": host_header,
                "User-Agent": f"Tori/{__version__}",
            },
        )
        response = connection.getresponse()
        body = response.read(maximum + 1)
        return response.status, dict(response.getheaders()), body
    finally:
        connection.close()


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, address: str, *, timeout: float) -> None:
        super().__init__(host, port, timeout=timeout)
        self._address = address

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._address, self.port), self.timeout, self.source_address
        )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, port: int, address: str, *, timeout: float) -> None:
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())
        self._address = address

    def connect(self) -> None:
        raw = socket.create_connection(
            (self._address, self.port), self.timeout, self.source_address
        )
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


class _ReadableHTMLParser(HTMLParser):
    _IGNORED = {
        "aside", "button", "footer", "form", "header", "nav", "noscript",
        "script", "style", "svg", "template",
    }
    _BLOCKS = {
        "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt",
        "figcaption", "footer", "h1", "h2", "h3", "h4", "h5", "h6",
        "header", "li", "main", "nav", "ol", "p", "pre", "section", "table",
        "td", "th", "tr", "ul",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._in_title = False
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[no-untyped-def]
        lowered = tag.lower()
        if lowered in self._IGNORED:
            self._ignored_depth += 1
        if lowered == "title" and self._ignored_depth == 0:
            self._in_title = True
        if lowered in self._BLOCKS and self._ignored_depth == 0:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered == "title":
            self._in_title = False
        if lowered in self._IGNORED and self._ignored_depth:
            self._ignored_depth -= 1
        if lowered in self._BLOCKS and self._ignored_depth == 0:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if self._in_title:
            self.title_parts.append(data)
        else:
            self.text_parts.append(data)


def _content_type(headers: Mapping[str, str]) -> str:
    value = _header(headers, "content-type")
    if value is None:
        raise SourceRetrievalError(
            "The public source did not identify a supported text format.",
            code="unsupported_content_type",
        )
    content_type = value.split(";", 1)[0].strip().lower()
    if content_type not in _SUPPORTED_TYPES:
        raise SourceRetrievalError(
            "The public source is not a supported text format.",
            code="unsupported_content_type",
        )
    return content_type


def _extract_content(body: bytes, content_type: str, *, maximum: int) -> tuple[str, str]:
    try:
        decoded = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceRetrievalError(
            "The public source is not valid UTF-8 text.", code="invalid_text"
        ) from exc
    if any(
        ord(character) < 32 and character not in {"\t", "\n", "\r"}
        or ord(character) == 127
        for character in decoded
    ):
        raise SourceRetrievalError(
            "The public source contains unsafe text controls.", code="invalid_text"
        )
    if content_type in {"text/html", "application/xhtml+xml"}:
        parser = _ReadableHTMLParser()
        try:
            parser.feed(decoded)
            parser.close()
        except Exception as exc:
            raise SourceRetrievalError(
                "The public source HTML could not be read.", code="invalid_text"
            ) from exc
        title = _collapse_inline(" ".join(parser.title_parts))[:500]
        text = _collapse_text("".join(parser.text_parts))
    else:
        title = ""
        text = _collapse_text(decoded)
    if not text:
        raise SourceRetrievalError(
            "The public source did not contain readable text.", code="empty_content"
        )
    return title, text[:maximum]


def _collapse_inline(value: str) -> str:
    return " ".join(value.split())


def _collapse_text(value: str) -> str:
    lines = [" ".join(line.split()) for line in value.splitlines()]
    return "\n".join(line for line in lines if line)


def _header(headers: Mapping[str, str], name: str) -> str | None:
    lowered = name.casefold()
    return next(
        (value for key, value in headers.items() if key.casefold() == lowered),
        None,
    )
