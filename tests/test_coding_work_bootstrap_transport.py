from __future__ import annotations

import inspect
import os
from pathlib import Path
import socket
import socketserver
import stat
import tempfile
import threading
import unittest

from tori.coding_work_bootstrap import _bootstrap_sandbox_argv
from tori.coding_work_bootstrap_transport import (
    BOOTSTRAP_LOOPBACK_ADDRESS,
    BOOTSTRAP_LOOPBACK_PORT,
    BOOTSTRAP_MODELS_URL,
    BOOTSTRAP_UPSTREAM_HOST,
    BOOTSTRAP_UPSTREAM_PORT,
    BootstrapEgressBounds,
    BootstrapEgressError,
    BootstrapLoopbackBridge,
    FixedOpenCodeBootstrapRelay,
)


class _EchoHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        while chunk := self.request.recv(4096):
            self.request.sendall(chunk)


class _EchoServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = False


class _FixtureRelay(FixedOpenCodeBootstrapRelay):
    def __init__(self, socket_path: Path, upstream_port: int, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(socket_path, **kwargs)
        self._upstream_port = upstream_port

    def _connect_fixed_upstream(self) -> socket.socket:
        return socket.create_connection(("127.0.0.1", self._upstream_port), timeout=2)


class BootstrapEgressTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        os.chmod(self.root, 0o700)

    def test_raw_tcp_traverses_loopback_unix_and_fixed_relay(self) -> None:
        upstream = _EchoServer(("127.0.0.1", 0), _EchoHandler)
        thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(upstream.server_close)
        self.addCleanup(upstream.shutdown)
        relay_path = self.root / "bootstrap.sock"
        relay = _FixtureRelay(relay_path, int(upstream.server_address[1]))
        relay.start()
        bridge = BootstrapLoopbackBridge(relay_path, _test_port=0)
        bridge.start()
        bridge_port = bridge.port
        try:
            client = socket.create_connection((BOOTSTRAP_LOOPBACK_ADDRESS, bridge.port), timeout=2)
            with client:
                client.sendall(b"synthetic tls bytes")
                client.shutdown(socket.SHUT_WR)
                self.assertEqual(client.recv(4096), b"synthetic tls bytes")
        finally:
            bridge.close()
            relay.close()
        self.assertFalse(os.path.lexists(relay_path))
        probe = socket.socket()
        try:
            self.assertNotEqual(probe.connect_ex((BOOTSTRAP_LOOPBACK_ADDRESS, bridge_port)), 0)
        finally:
            probe.close()
        self.assertEqual(relay.destination, (BOOTSTRAP_UPSTREAM_HOST, BOOTSTRAP_UPSTREAM_PORT))
        self.assertEqual(relay.audit[0].outcome, "preflight_success")
        successful = [item for item in relay.audit if item.outcome == "success"]
        self.assertEqual(len(successful), 1)
        self.assertEqual(successful[0].destination_host, "models.opencode.ai")
        self.assertEqual(successful[0].destination_port, 443)
        self.assertEqual(successful[0].inbound_bytes, len(b"synthetic tls bytes"))
        self.assertEqual(successful[0].outbound_bytes, len(b"synthetic tls bytes"))

    def test_destination_is_not_caller_configurable_and_hostile_socket_fails_closed(self) -> None:
        parameters = inspect.signature(FixedOpenCodeBootstrapRelay).parameters
        self.assertNotIn("host", parameters)
        self.assertNotIn("port", parameters)
        self.assertNotIn("destination", parameters)
        hostile = self.root / "bootstrap.sock"
        hostile.write_text("valuable", encoding="utf-8")
        os.chmod(hostile, 0o600)
        relay = FixedOpenCodeBootstrapRelay(hostile)
        with self.assertRaises(BootstrapEgressError) as captured:
            relay.start()
        self.assertEqual(captured.exception.code, "unsafe_socket_path")
        self.assertEqual(hostile.read_text(encoding="utf-8"), "valuable")

    def test_connection_and_byte_bounds_are_enforced_without_payload_audit(self) -> None:
        upstream = _EchoServer(("127.0.0.1", 0), _EchoHandler)
        thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(upstream.server_close)
        self.addCleanup(upstream.shutdown)
        relay_path = self.root / "bounded.sock"
        bounds = BootstrapEgressBounds(
            max_connections=1,
            max_concurrent_connections=1,
            max_bytes_each_direction=4,
            connection_timeout_seconds=1,
            relay_lifetime_seconds=5,
        )
        with _FixtureRelay(relay_path, int(upstream.server_address[1]), bounds=bounds) as relay:
            with BootstrapLoopbackBridge(relay_path, _test_port=0) as bridge:
                client = socket.create_connection(("127.0.0.1", bridge.port), timeout=2)
                with client:
                    client.sendall(b"payload-not-retained")
                    client.shutdown(socket.SHUT_WR)
                    while client.recv(4096):
                        pass
        record = relay.audit[-1]
        self.assertEqual(record.outcome, "failed:byte_limit")
        self.assertGreater(record.inbound_bytes, 4)
        self.assertFalse(hasattr(record, "payload"))

    def test_sandbox_plan_has_private_network_fixed_hosts_and_no_dns(self) -> None:
        stage = self.root / "stage"
        isolated = self.root / "isolated"
        for path in (
            stage / "data", stage / "cache", stage / "state",
            isolated / "home", isolated / "config", isolated / "tmp",
            isolated / "workspace", isolated / "ipc",
        ):
            path.mkdir(parents=True, mode=0o700, exist_ok=True)
            os.chmod(path, 0o700)
        files = {}
        for name, content in (
            ("opencode", b"binary"),
            ("bridge.py", b"source"),
            ("hosts", b"127.0.0.1 models.opencode.ai\n"),
            ("resolv.conf", b""),
            ("nsswitch.conf", b"hosts: files\n"),
        ):
            path = self.root / name
            path.write_bytes(content)
            os.chmod(path, 0o700 if name == "opencode" else 0o600)
            files[name] = path
        socket_path = isolated / "ipc/bootstrap-egress.sock"
        argv = _bootstrap_sandbox_argv(
            Path("/usr/bin/bwrap"), files["opencode"], files["bridge.py"],
            socket_path, files["hosts"], files["resolv.conf"],
            files["nsswitch.conf"], stage, isolated,
            ("/harness/opencode", "debug", "config", "--pure"),
        )
        self.assertIn("--unshare-all", argv)
        self.assertNotIn("--share-net", argv)
        self.assertIn("--clearenv", argv)
        config_index = argv.index("/config")
        self.assertEqual(argv[config_index - 2 : config_index + 1], (
            "--bind", str(isolated / "config"), "/config",
        ))
        writable_sources = {
            argv[index + 1]
            for index, value in enumerate(argv)
            if value == "--bind"
        }
        self.assertEqual(writable_sources, {
            str(isolated / "home"),
            str(isolated / "config"),
            str(stage / "data"),
            str(stage / "cache"),
            str(stage / "state"),
            str(isolated / "tmp"),
        })
        self.assertEqual(files["hosts"].read_text(encoding="ascii"), "127.0.0.1 models.opencode.ai\n")
        self.assertEqual(files["resolv.conf"].read_bytes(), b"")
        self.assertEqual(files["nsswitch.conf"].read_text(encoding="ascii"), "hosts: files\n")
        self.assertNotIn("CONNECT", argv)
        self.assertNotIn("models.opencode.ai", argv)
        self.assertNotIn(str(Path.home()), "\n".join(argv))
        self.assertEqual(BOOTSTRAP_LOOPBACK_PORT, 11_443)
        self.assertEqual(BOOTSTRAP_MODELS_URL, "https://models.opencode.ai:11443")
        models_url_index = argv.index("OPENCODE_MODELS_URL")
        self.assertEqual(argv[models_url_index + 1], BOOTSTRAP_MODELS_URL)
        command_index = argv.index("--", argv.index("--chdir"))
        self.assertEqual(
            argv[command_index + 1 :],
            (
                "/usr/bin/python3", "/harness/bootstrap_transport.py",
                "--unix-socket", "/harness/ipc/bootstrap-egress.sock", "--",
                "/harness/opencode", "debug", "config", "--pure",
            ),
        )


if __name__ == "__main__":
    unittest.main()
