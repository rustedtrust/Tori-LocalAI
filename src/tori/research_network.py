"""Fail-closed network broker for the Research Worker namespace.

The worker lives in a private Linux network namespace.  Its only usable TCP
listeners are two Tori-owned loopback relays: an explicit HTTP CONNECT proxy
and an Ollama relay.  Both cross the namespace over a Unix socket.  The outer
broker resolves public names once, validates every resolved address, and
connects the validated numeric sockaddr, closing the DNS-rebinding gap between
application validation and connection establishment.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import argparse
import ipaddress
import json
import os
from pathlib import Path
import selectors
import socket
import socketserver
import subprocess
import sys
import threading
from urllib.parse import parse_qs, urlsplit


MAX_HANDSHAKE = 4096
MAX_HTTP_HEADER = 64 * 1024
MAX_OLLAMA_REQUEST_BODY = 16 * 1024 * 1024
METADATA_ADDRESSES = frozenset({"169.254.169.254", "100.100.100.200"})


class ResearchNetworkError(RuntimeError):
    code = "research_network_denied"


def public_sockaddr(host: str, port: int) -> tuple[int, int, int, tuple[object, ...]]:
    """Resolve and return one validated numeric public destination."""

    if not host or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ResearchNetworkError("The requested public destination is invalid.")
    try:
        values = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ResearchNetworkError("The public destination could not be resolved.") from exc
    if not values:
        raise ResearchNetworkError("The public destination did not resolve.")
    validated: list[tuple[int, int, int, tuple[object, ...]]] = []
    for family, socktype, protocol, _canonical, sockaddr in values:
        try:
            address = ipaddress.ip_address(str(sockaddr[0]).split("%", 1)[0])
        except ValueError as exc:
            raise ResearchNetworkError("The resolver returned an invalid address.") from exc
        if str(address) in METADATA_ADDRESSES or not address.is_global:
            raise ResearchNetworkError("The destination resolved to a non-public address.")
        validated.append((family, socktype, protocol, sockaddr))
    return validated[0]


def connect_public(host: str, port: int, *, timeout: float = 15.0) -> socket.socket:
    family, socktype, protocol, sockaddr = public_sockaddr(host, port)
    connection = socket.socket(family, socktype, protocol)
    connection.settimeout(timeout)
    try:
        connection.connect(sockaddr)
    except Exception:
        connection.close()
        raise
    connection.settimeout(None)
    return connection


def _relay(left: socket.socket, right: socket.socket) -> None:
    selector = selectors.DefaultSelector()
    try:
        left.setblocking(False)
        right.setblocking(False)
        selector.register(left, selectors.EVENT_READ, right)
        selector.register(right, selectors.EVENT_READ, left)
        while selector.get_map():
            for key, _mask in selector.select(timeout=30):
                source = key.fileobj
                target = key.data
                try:
                    data = source.recv(65536)
                except (BlockingIOError, InterruptedError):
                    continue
                if not data:
                    try:
                        target.shutdown(socket.SHUT_WR)
                    except OSError:
                        pass
                    selector.unregister(source)
                    continue
                view = memoryview(data)
                while view:
                    try:
                        sent = target.send(view)
                    except (BlockingIOError, InterruptedError):
                        continue
                    view = view[sent:]
    finally:
        selector.close()
        left.close()
        right.close()


def _relay_response(source: socket.socket, destination: socket.socket) -> None:
    """Copy a response in one direction; never reopen worker request authority."""

    try:
        while True:
            data = source.recv(65536)
            if not data:
                return
            destination.sendall(data)
    finally:
        source.close()
        destination.close()


def _bounded_request_body(
    connection: socket.socket, header_lines: list[bytes], initial: bytes
) -> bytes:
    """Read exactly one non-chunked request body and reject pipelined bytes."""

    lengths: list[int] = []
    for line in header_lines:
        name, separator, value = line.partition(b":")
        if not separator:
            raise ResearchNetworkError("The Ollama request header is malformed.")
        lowered = name.strip().lower()
        if lowered == b"transfer-encoding":
            raise ResearchNetworkError("Chunked Ollama requests are not authorized.")
        if lowered == b"content-length":
            try:
                lengths.append(int(value.strip().decode("ascii")))
            except (UnicodeDecodeError, ValueError) as exc:
                raise ResearchNetworkError("The Ollama content length is invalid.") from exc
    if len(lengths) > 1 or (lengths and not 0 <= lengths[0] <= MAX_OLLAMA_REQUEST_BODY):
        raise ResearchNetworkError("The Ollama content length is invalid.")
    expected = lengths[0] if lengths else 0
    if len(initial) > expected:
        raise ResearchNetworkError("Pipelined Ollama requests are not authorized.")
    body = bytearray(initial)
    while len(body) < expected:
        data = connection.recv(min(65536, expected - len(body)))
        if not data:
            raise ResearchNetworkError("The Ollama request body ended early.")
        body.extend(data)
    return bytes(body)


def _read_line(connection: socket.socket, maximum: int = MAX_HANDSHAKE) -> bytes:
    data = bytearray()
    while len(data) <= maximum:
        chunk = connection.recv(1)
        if not chunk:
            break
        data.extend(chunk)
        if data.endswith(b"\n"):
            return bytes(data)
    raise ResearchNetworkError("The network broker handshake is invalid.")


class _BrokerHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        server = self.server
        assert isinstance(server, _UnixBrokerServer)
        try:
            document = json.loads(_read_line(self.request).decode("utf-8"))
            if not isinstance(document, dict):
                raise ResearchNetworkError("The network broker request is invalid.")
            kind = document.get("kind")
            if kind == "public":
                host, port = document.get("host"), document.get("port")
                if not isinstance(host, str) or isinstance(port, bool) or not isinstance(port, int):
                    raise ResearchNetworkError("The public broker request is invalid.")
                if port not in {80, 443}:
                    raise ResearchNetworkError("Public research egress is limited to HTTP and HTTPS ports.")
                destination = connect_public(host, port)
            elif kind == "ollama":
                destination = socket.create_connection(server.ollama_address, timeout=10)
                destination.settimeout(None)
            elif kind == "searxng" and server.searxng_address is not None:
                destination = socket.create_connection(server.searxng_address, timeout=10)
                destination.settimeout(None)
            else:
                raise ResearchNetworkError("The broker operation is not authorized.")
            self.request.sendall(b"OK\n")
            _relay(self.request, destination)
        except Exception:
            try:
                self.request.sendall(b"DENIED\n")
            except OSError:
                pass


class _UnixBrokerServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def __init__(
        self, path: str, ollama_address: tuple[str, int],
        searxng_address: tuple[str, int] | None = None,
    ) -> None:
        self.ollama_address = ollama_address
        self.searxng_address = searxng_address
        super().__init__(path, _BrokerHandler)


@contextmanager
def public_egress_broker(
    path: Path, ollama_address: tuple[str, int],
    searxng_address: tuple[str, int] | None = None,
) -> Iterator[None]:
    """Run one per-job broker and remove its Unix socket on exit."""

    socket_path = Path(path)
    if socket_path.exists() or socket_path.is_symlink():
        raise ResearchNetworkError("The Research broker socket path already exists.")
    server = _UnixBrokerServer(str(socket_path), ollama_address, searxng_address)
    os.chmod(socket_path, 0o600)
    thread = threading.Thread(target=server.serve_forever, name="tori-research-egress", daemon=True)
    thread.start()
    try:
        yield
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        try:
            socket_path.unlink()
        except FileNotFoundError:
            pass


class _ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = False
    daemon_threads = True


def _open_broker(path: str, document: dict[str, object]) -> socket.socket:
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.connect(path)
    connection.sendall(json.dumps(document, separators=(",", ":")).encode() + b"\n")
    if _read_line(connection) != b"OK\n":
        connection.close()
        raise ResearchNetworkError("The outer network broker denied the destination.")
    return connection


class _ConnectProxyHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        server = self.server
        assert isinstance(server, _InnerProxyServer)
        try:
            header = bytearray()
            while b"\r\n\r\n" not in header and len(header) <= MAX_HTTP_HEADER:
                chunk = self.request.recv(4096)
                if not chunk:
                    return
                header.extend(chunk)
            if len(header) > MAX_HTTP_HEADER:
                raise ResearchNetworkError("The proxy request header is too large.")
            head, body = bytes(header).split(b"\r\n\r\n", 1)
            lines = head.split(b"\r\n")
            method, target, version = lines[0].decode("ascii").split(" ", 2)
            if method.upper() == "CONNECT":
                host, separator, port_text = target.rpartition(":")
                if not separator:
                    raise ResearchNetworkError("CONNECT requires an explicit port.")
                destination = _open_broker(server.broker_path, {
                    "kind": "public", "host": host.strip("[]"), "port": int(port_text),
                })
                self.request.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                _relay(self.request, destination)
                return
            parsed = urlsplit(target)
            if parsed.scheme != "http" or parsed.hostname is None:
                raise ResearchNetworkError("Only HTTP absolute-form or HTTPS CONNECT is supported.")
            port = parsed.port or 80
            destination = _open_broker(server.broker_path, {
                "kind": "public", "host": parsed.hostname, "port": port,
            })
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            destination.sendall(f"{method} {path} {version}\r\n".encode("ascii") + b"\r\n".join(lines[1:]) + b"\r\n\r\n" + body)
            _relay(self.request, destination)
        except Exception:
            try:
                self.request.sendall(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
            except OSError:
                pass


class _InnerProxyServer(_ThreadingTCPServer):
    def __init__(self, address: tuple[str, int], broker_path: str) -> None:
        self.broker_path = broker_path
        super().__init__(address, _ConnectProxyHandler)


class _OllamaRelayHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        server = self.server
        assert isinstance(server, _InnerOllamaServer)
        try:
            header = bytearray()
            while b"\r\n\r\n" not in header and len(header) <= MAX_HTTP_HEADER:
                chunk = self.request.recv(4096)
                if not chunk:
                    return
                header.extend(chunk)
            if len(header) > MAX_HTTP_HEADER:
                raise ResearchNetworkError("The Ollama request header is too large.")
            head, body = bytes(header).split(b"\r\n\r\n", 1)
            lines = head.split(b"\r\n")
            method, target, version = lines[0].decode("ascii").split(" ", 2)
            allowed = {
                ("POST", "/api/chat"), ("POST", "/api/generate"),
                ("POST", "/api/embed"), ("POST", "/api/embeddings"),
                ("POST", "/v1/chat/completions"), ("POST", "/v1/embeddings"),
                ("GET", "/api/tags"),
            }
            path = urlsplit(target).path
            if (method.upper(), path) not in allowed:
                raise ResearchNetworkError("The Ollama operation is not authorized for research.")
            self.request.settimeout(30)
            body = _bounded_request_body(self.request, lines[1:], body)
            destination = _open_broker(server.broker_path, {"kind": "ollama"})
            retained = [line for line in lines[1:] if not line.lower().startswith(b"connection:")]
            destination.sendall(
                f"{method} {target} {version}\r\n".encode("ascii")
                + b"\r\n".join(retained) + b"\r\nConnection: close\r\n\r\n" + body
            )
            # Ollama treats a propagated TCP half-close as request-context
            # cancellation even after a complete bounded request.  Keep the
            # one-shot broker channel open while reading the response; the
            # injected ``Connection: close`` makes the response self-terminating.
            _relay_response(destination, self.request)
        except Exception:
            try:
                self.request.sendall(
                    b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\nContent-Length: 0\r\n\r\n"
                )
            except OSError:
                pass


class _InnerOllamaServer(_ThreadingTCPServer):
    def __init__(self, address: tuple[str, int], broker_path: str) -> None:
        self.broker_path = broker_path
        super().__init__(address, _OllamaRelayHandler)


class _SearxRelayHandler(socketserver.BaseRequestHandler):
    """Permit one bounded JSON search request to the configured SearXNG only."""

    def handle(self) -> None:
        server = self.server
        assert isinstance(server, _InnerSearxServer)
        try:
            header = bytearray()
            while b"\r\n\r\n" not in header and len(header) <= MAX_HTTP_HEADER:
                chunk = self.request.recv(4096)
                if not chunk:
                    return
                header.extend(chunk)
            if len(header) > MAX_HTTP_HEADER:
                raise ResearchNetworkError("The SearXNG request header is too large.")
            head, body = bytes(header).split(b"\r\n\r\n", 1)
            if body:
                raise ResearchNetworkError("SearXNG request bodies are not authorized.")
            lines = head.split(b"\r\n")
            method, target, version = lines[0].decode("ascii").split(" ", 2)
            parsed = urlsplit(target)
            parameters = parse_qs(parsed.query, keep_blank_values=True)
            if (
                method != "GET" or parsed.path != "/search"
                or set(parameters) - {"q", "format", "categories"}
                or len(parameters.get("q", [])) != 1
                or parameters.get("format") != ["json"]
                or parameters.get("categories") != ["general"]
                or not 1 <= len(parameters["q"][0]) <= 8000
            ):
                raise ResearchNetworkError("The SearXNG operation is not authorized.")
            destination = _open_broker(server.broker_path, {"kind": "searxng"})
            retained = [
                line for line in lines[1:]
                if not line.lower().startswith((b"connection:", b"host:", b"proxy-"))
            ]
            destination.sendall(
                f"GET {target} {version}\r\nHost: tori-searxng\r\n".encode("ascii")
                + b"\r\n".join(retained) + b"\r\nConnection: close\r\n\r\n"
            )
            _relay_response(destination, self.request)
        except Exception:
            try:
                self.request.sendall(
                    b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\nContent-Length: 0\r\n\r\n"
                )
            except OSError:
                pass


class _InnerSearxServer(_ThreadingTCPServer):
    def __init__(self, address: tuple[str, int], broker_path: str) -> None:
        self.broker_path = broker_path
        super().__init__(address, _SearxRelayHandler)


def research_worker_environment(model: str, embedding_model: str) -> dict[str, str]:
    """Build the complete allowlisted child environment; inherit nothing ambient."""

    return {
        "HOME": "/tmp/tori-research-home",
        "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "TMPDIR": "/tmp", "PYTHONUNBUFFERED": "1",
        "HTTP_PROXY": "http://127.0.0.1:18080",
        "HTTPS_PROXY": "http://127.0.0.1:18080",
        "ALL_PROXY": "",
        "NO_PROXY": "127.0.0.1,localhost",
        "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
        "SEARXNG_URL": "http://127.0.0.1:18081",
        "LLM_PROVIDER": "ollama",
        "FAST_LLM": f"ollama:{model}",
        "SMART_LLM": f"ollama:{model}",
        "STRATEGIC_LLM": f"ollama:{model}",
        "EMBEDDING": f"ollama:{embedding_model}",
        "RETRIEVER": "custom",
        "TORI_RETRIEVER": "authoritative_source",
        "LANGCHAIN_TRACING_V2": "false",
    }


def run_child(
    broker_path: str, worker: list[str], *, model: str, embedding_model: str
) -> int:
    """Run relays and the real worker inside bwrap's private network."""

    proxy = _InnerProxyServer(("127.0.0.1", 18080), broker_path)
    ollama = _InnerOllamaServer(("127.0.0.1", 11434), broker_path)
    searxng = _InnerSearxServer(("127.0.0.1", 18081), broker_path)
    threads = [
        threading.Thread(target=proxy.serve_forever, daemon=True),
        threading.Thread(target=ollama.serve_forever, daemon=True),
        threading.Thread(target=searxng.serve_forever, daemon=True),
    ]
    for thread in threads:
        thread.start()
    environment = research_worker_environment(model, embedding_model)
    try:
        completed = subprocess.run(worker, env=environment, check=False)
        return completed.returncode
    finally:
        proxy.shutdown(); ollama.shutdown(); searxng.shutdown()
        proxy.server_close(); ollama.server_close(); searxng.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--broker")
    parser.add_argument("--model")
    parser.add_argument("--embedding-model")
    parser.add_argument("worker", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if (
        not args.child or not args.broker or not args.model or not args.embedding_model
        or not args.worker or args.worker[0] != "--"
    ):
        parser.error("only the private-namespace child mode is supported")
    return run_child(
        args.broker, args.worker[1:], model=args.model,
        embedding_model=args.embedding_model,
    )


if __name__ == "__main__":
    raise SystemExit(main())
