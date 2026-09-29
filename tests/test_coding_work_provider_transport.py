from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import json
import os
from pathlib import Path
import runpy
import socket
import stat
import sys
from tempfile import TemporaryDirectory
import threading
import unittest

from tori.coding_work_provider_transport import (
    CHAT_COMPLETIONS_PATH,
    NarrowOpenAIProviderRelay,
    OpenAICompatibleInferencePolicy,
    ProviderLoopbackBridge,
    ProviderTransportError,
)


class _UpstreamHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self.server.requests.append(  # type: ignore[attr-defined]
            {
                "method": self.command,
                "path": self.path,
                "headers": {key.lower(): value for key, value in self.headers.items()},
                "body": json.loads(body),
            }
        )
        entered = getattr(self.server, "entered", None)
        release = getattr(self.server, "release", None)
        if entered is not None and release is not None:
            entered.set()
            release.wait(timeout=5)
        payload = getattr(
            self.server,
            "payload",
            b'{"id":"local-proof","choices":[{"message":{"role":"assistant","content":"ok"}}]}',
        )
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class _UpstreamServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _UpstreamHandler)
        self.requests: list[dict[str, object]] = []
        self.payload = b'{"id":"local-proof","choices":[{"message":{"role":"assistant","content":"ok"}}]}'
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)

    def __enter__(self) -> "_UpstreamServer":
        self.thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.shutdown()
        self.server_close()
        self.thread.join(timeout=5)


class CodingWorkProviderTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory(prefix="tori-provider-transport-test-")
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_exact_chat_completion_reaches_only_fixed_upstream(self) -> None:
        with _UpstreamServer() as upstream:
            policy = self._policy(upstream)
            with NarrowOpenAIProviderRelay(self.root / "relay.sock", policy) as relay:
                with ProviderLoopbackBridge(relay.socket_path) as bridge:
                    connection = http.client.HTTPConnection("127.0.0.1", bridge.port, timeout=3)
                    body = json.dumps(
                        {"model": "qwen3.8:latest", "messages": [{"role": "user", "content": "hi"}]}
                    )
                    connection.request(
                        "POST",
                        CHAT_COMPLETIONS_PATH,
                        body=body,
                        headers={
                            "Content-Type": "application/json",
                            "Host": "attacker.invalid:65535",
                            "Authorization": "Bearer sandbox-secret-must-not-cross",
                        },
                    )
                    response = connection.getresponse()
                    document = json.loads(response.read())
                    connection.close()

                self.assertEqual(response.status, 200)
                self.assertEqual(document["choices"][0]["message"]["content"], "ok")
                self.assertEqual(len(upstream.requests), 1)
                request = upstream.requests[0]
                self.assertEqual(request["path"], CHAT_COMPLETIONS_PATH)
                headers = request["headers"]
                self.assertNotIn("authorization", headers)
                self.assertEqual(headers["host"], f"127.0.0.1:{upstream.server_port}")
                self.assertEqual(relay.audit[-1].outcome, "allowed")

    def test_administrative_paths_methods_and_models_are_denied(self) -> None:
        with _UpstreamServer() as upstream:
            with NarrowOpenAIProviderRelay(
                self.root / "relay.sock", self._policy(upstream)
            ) as relay:
                with ProviderLoopbackBridge(relay.socket_path) as bridge:
                    attempts = (
                        ("GET", CHAT_COMPLETIONS_PATH, None, "method_denied"),
                        ("POST", "/api/pull", self._body(), "path_denied"),
                        ("POST", "/v1/models", self._body(), "path_denied"),
                        ("POST", "http://127.0.0.1:9999/v1/chat/completions", self._body(), "path_denied"),
                        (
                            "POST",
                            CHAT_COMPLETIONS_PATH,
                            self._body(model="another-model"),
                            "model_denied",
                        ),
                    )
                    for method, path, body, code in attempts:
                        with self.subTest(method=method, path=path, code=code):
                            status, document = self._request(bridge.port, method, path, body)
                            self.assertIn(status, {403, 405})
                            self.assertEqual(document["error"]["code"], code)

                self.assertEqual(upstream.requests, [])
                self.assertEqual(len(relay.audit), len(attempts))
                self.assertTrue(all(item.outcome.startswith("rejected:") for item in relay.audit))

    def test_malformed_chunked_and_oversized_requests_fail_closed(self) -> None:
        with _UpstreamServer() as upstream:
            policy = OpenAICompatibleInferencePolicy(
                "127.0.0.1",
                upstream.server_port,
                "qwen3.8:latest",
                max_request_bytes=64,
            )
            with NarrowOpenAIProviderRelay(self.root / "relay.sock", policy) as relay:
                with ProviderLoopbackBridge(relay.socket_path) as bridge:
                    malformed = self._raw(
                        bridge.port,
                        b"BROKEN\r\nHost: ignored\r\nContent-Length: 0\r\n\r\n",
                    )
                    chunked = self._raw(
                        bridge.port,
                        b"POST /v1/chat/completions HTTP/1.1\r\n"
                        b"Content-Type: application/json\r\n"
                        b"Transfer-Encoding: chunked\r\n\r\n0\r\n\r\n",
                    )
                    oversized = self._raw(
                        bridge.port,
                        b"POST /v1/chat/completions HTTP/1.1\r\n"
                        b"Content-Type: application/json\r\nContent-Length: 65\r\n\r\n",
                    )

                self.assertIn(b"400 Bad Request", malformed)
                self.assertIn(b"transfer_encoding_denied", chunked)
                self.assertIn(b"413 Payload Too Large", oversized)
                self.assertEqual(upstream.requests, [])

    def test_existing_socket_path_is_never_replaced(self) -> None:
        path = self.root / "relay.sock"
        path.write_text("valuable", encoding="utf-8")
        relay = NarrowOpenAIProviderRelay(
            path,
            OpenAICompatibleInferencePolicy("127.0.0.1", 11434, "qwen3.8:latest"),
        )
        with self.assertRaises(ProviderTransportError) as captured:
            relay.start()
        self.assertEqual(captured.exception.code, "unsafe_socket_path")
        self.assertEqual(path.read_text(encoding="utf-8"), "valuable")

    def test_owned_stale_socket_recovers_but_hostile_or_active_socket_fails_closed(self) -> None:
        token = "a" * 64
        path = self.root / "relay.sock"
        policy = OpenAICompatibleInferencePolicy(
            "127.0.0.1", 11434, "qwen3.8:latest"
        )
        initial = NarrowOpenAIProviderRelay(path, policy, ownership_token=token)
        initial.start()
        initial.close()
        stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        stale.bind(str(path))
        stale.close()
        path.chmod(0o600)
        recovered = NarrowOpenAIProviderRelay(path, policy, ownership_token=token)
        recovered.start()
        self.assertTrue(stat.S_ISSOCK(path.lstat().st_mode))

        active = NarrowOpenAIProviderRelay(path, policy, ownership_token=token)
        with self.assertRaises(ProviderTransportError) as active_error:
            active.start()
        self.assertEqual(active_error.exception.code, "already_running")
        recovered.close()

        owner = path.with_name(path.name + ".owner")
        owner.write_text('{"schema":1,"token":"' + "b" * 64 + '"}', encoding="utf-8")
        hostile = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        hostile.bind(str(path))
        hostile.close()
        refused = NarrowOpenAIProviderRelay(path, policy, ownership_token=token)
        with self.assertRaises(ProviderTransportError) as hostile_error:
            refused.start()
        self.assertEqual(hostile_error.exception.code, "unsafe_socket_path")
        self.assertTrue(stat.S_ISSOCK(path.lstat().st_mode))

    def test_explicit_stale_recovery_is_proven_and_foreign_replacement_is_preserved(self) -> None:
        token = "c" * 64
        path = self.root / "relay.sock"
        policy = OpenAICompatibleInferencePolicy(
            "127.0.0.1", 11434, "qwen3.8:latest"
        )
        relay = NarrowOpenAIProviderRelay(path, policy, ownership_token=token)
        relay.start()
        relay.close()

        stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        stale.bind(str(path))
        stale.close()
        path.chmod(0o600)
        NarrowOpenAIProviderRelay(
            path, policy, ownership_token=token
        ).recover_stale()
        self.assertFalse(os.path.lexists(path))

        active = NarrowOpenAIProviderRelay(path, policy, ownership_token=token)
        active.start()
        path.unlink()
        foreign = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        foreign.bind(str(path))
        path.chmod(0o600)
        with self.assertRaises(ProviderTransportError) as replaced:
            active.close()
        self.assertEqual(replaced.exception.code, "unsafe_socket_path")
        self.assertTrue(stat.S_ISSOCK(path.lstat().st_mode))
        foreign.close()
        path.unlink()

    def test_oversized_upstream_response_is_atomic_and_concurrency_is_bounded(self) -> None:
        with _UpstreamServer() as upstream:
            upstream.payload = b"x" * 1024
            policy = OpenAICompatibleInferencePolicy(
                "127.0.0.1", upstream.server_port, "qwen3.8:latest",
                max_response_bytes=64, timeout_seconds=3,
            )
            with NarrowOpenAIProviderRelay(self.root / "relay.sock", policy) as relay:
                with ProviderLoopbackBridge(relay.socket_path) as bridge:
                    raw = self._raw_request(bridge.port, self._body().encode())
            self.assertIn(b"502 Bad Gateway", raw)
            self.assertIn(b"response_too_large", raw)
            self.assertNotIn(b"200 OK", raw)

        with _UpstreamServer() as upstream:
            upstream.entered = threading.Event()
            upstream.release = threading.Event()
            with NarrowOpenAIProviderRelay(
                self.root / "bounded.sock",
                self._policy(upstream),
                max_concurrent_requests=1,
            ) as relay:
                with ProviderLoopbackBridge(relay.socket_path) as bridge:
                    first: list[tuple[int, object]] = []
                    thread = threading.Thread(
                        target=lambda: first.append(
                            self._request(
                                bridge.port, "POST", CHAT_COMPLETIONS_PATH, self._body()
                            )
                        )
                    )
                    thread.start()
                    self.assertTrue(upstream.entered.wait(timeout=2))
                    status, document = self._request(
                        bridge.port, "POST", CHAT_COMPLETIONS_PATH, self._body()
                    )
                    self.assertEqual(status, 503)
                    self.assertEqual(document["error"]["code"], "concurrency_limit")
                    upstream.release.set()
                    thread.join(timeout=3)
                    self.assertEqual(first[0][0], 200)

    def test_symlink_socket_parent_is_rejected(self) -> None:
        real = self.root / "real"
        real.mkdir()
        linked = self.root / "linked"
        linked.symlink_to(real, target_is_directory=True)
        relay = NarrowOpenAIProviderRelay(
            linked / "relay.sock",
            OpenAICompatibleInferencePolicy("127.0.0.1", 11434, "qwen3.8:latest"),
        )
        with self.assertRaises(ProviderTransportError) as captured:
            relay.start()
        self.assertEqual(captured.exception.code, "unsafe_socket_path")
        self.assertEqual(list(real.iterdir()), [])

    def test_policy_refuses_non_loopback_upstream(self) -> None:
        with self.assertRaisesRegex(ValueError, "loopback"):
            OpenAICompatibleInferencePolicy("192.168.1.10", 11434, "qwen3.8:latest")

    def test_acceptance_acp_wait_uses_time_not_notification_count(self) -> None:
        acceptance = runpy.run_path(
            str(Path(__file__).resolve().parents[1] / "scripts/verify-opencode-transport"),
            run_name="tori_transport_acceptance_test",
        )
        acp_class = acceptance["_ACP"]
        code = (
            "import json,sys\n"
            "request=json.loads(sys.stdin.readline())\n"
            "for _ in range(500):\n"
            " print(json.dumps({'jsonrpc':'2.0','method':'session/update','params':"
            "{'update':{'sessionUpdate':'progress'}}}), flush=True)\n"
            "print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':{}}), flush=True)\n"
        )
        acp = acp_class(
            [sys.executable, "-u", "-c", code],
            {"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        )
        try:
            response = acp.call(1, "session/prompt", {}, timeout_seconds=5)
            self.assertEqual(response["result"], {})
            self.assertEqual(acp.update_types, {"progress"})
        finally:
            acp.close()

    def test_acceptance_acp_timeout_is_bounded_and_cleanup_is_idempotent(self) -> None:
        acceptance = runpy.run_path(
            str(Path(__file__).resolve().parents[1] / "scripts/verify-opencode-transport"),
            run_name="tori_transport_acceptance_timeout_test",
        )
        acp_class = acceptance["_ACP"]
        timeout_class = acceptance["_ACPCallTimeout"]
        code = (
            "import json,sys,time\n"
            "json.loads(sys.stdin.readline())\n"
            "print(json.dumps({'jsonrpc':'2.0','method':'session/update','params':"
            "{'update':{'sessionUpdate':'progress'}}}), flush=True)\n"
            "time.sleep(30)\n"
        )
        acp = acp_class(
            [sys.executable, "-u", "-c", code],
            {"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        )
        with self.assertRaises(timeout_class) as captured:
            acp.call(1, "session/prompt", {}, timeout_seconds=0.1)
        self.assertIn("notifications=1", str(captured.exception))
        self.assertIn("ACP process=alive", str(captured.exception))
        acp.close()
        acp.close()
        self.assertIsNotNone(acp.process.poll())
        self.assertEqual(acceptance["ACP_CONTROL_TIMEOUT_SECONDS"], 30.0)
        self.assertEqual(acceptance["ACP_MODEL_TASK_TIMEOUT_SECONDS"], 900.0)

    @staticmethod
    def _policy(upstream: _UpstreamServer) -> OpenAICompatibleInferencePolicy:
        return OpenAICompatibleInferencePolicy(
            "127.0.0.1", upstream.server_port, "qwen3.8:latest", timeout_seconds=3
        )

    @staticmethod
    def _body(*, model: str = "qwen3.8:latest") -> str:
        return json.dumps({"model": model, "messages": []})

    @staticmethod
    def _request(port: int, method: str, path: str, body: str | None) -> tuple[int, object]:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        headers = {"Content-Type": "application/json"} if body is not None else {}
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        document = json.loads(response.read())
        status = response.status
        connection.close()
        return status, document

    @staticmethod
    def _raw(port: int, payload: bytes) -> bytes:
        client = socket.create_connection(("127.0.0.1", port), timeout=3)
        client.sendall(payload)
        client.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            chunk = client.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
        client.close()
        return b"".join(chunks)

    @staticmethod
    def _raw_request(port: int, body: bytes) -> bytes:
        request = (
            b"POST /v1/chat/completions HTTP/1.1\r\n"
            b"Content-Type: application/json\r\n"
            + f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
            + body
        )
        return CodingWorkProviderTransportTests._raw(port, request)


if __name__ == "__main__":
    unittest.main()
