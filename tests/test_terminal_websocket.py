"""Real HTTP upgrade tests on the existing Tori request handler."""

from __future__ import annotations

import base64
import http.client
import json
from pathlib import Path
import select
import secrets
import socket
import struct
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from tori.execution_policy import ExecutionPolicyService, ExecutionRequest, ExecutionScope
from tori.terminal_broker import TerminalBroker
from tori.terminal_receipts import TerminalReceiptStore
from tori.terminal_websocket import TerminalBrowserSessions
from tori.terminal_authority import TerminalLocalAuthority
from tori.terminal_launch import TerminalLaunchService
from tori.request_origin import RequestOrigin
from tori.web import _handler_for, _LocalWebServer


def client_frame(opcode: int, data: bytes) -> bytes:
    mask = secrets.token_bytes(4)
    size = len(data)
    header = bytes((0x80 | opcode, 0x80 | size)) if size < 126 else bytes((0x80 | opcode, 0x80 | 126)) + struct.pack("!H", size)
    return header + mask + bytes(value ^ mask[i % 4] for i, value in enumerate(data))


def read_server_frame(stream: object) -> tuple[int, bytes]:
    header = stream.read(2)
    if len(header) != 2:
        raise EOFError
    size = header[1] & 127
    if size == 126:
        size = struct.unpack("!H", stream.read(2))[0]
    elif size == 127:
        size = struct.unpack("!Q", stream.read(8))[0]
    return header[0] & 15, stream.read(size)


class _App:
    def __init__(self, broker: TerminalBroker) -> None:
        self.port = 0
        self.csrf_token = secrets.token_urlsafe(32)
        self.terminal_broker = broker
        self.terminal_launcher = TerminalLaunchService(broker._policy, broker)
        self.terminal_policy = broker._policy
        self.terminal_browser_sessions = TerminalBrowserSessions()
        self.restore_pending = False
        self.active_chat_id = "chat-a"

    def terminal_conversation_id(self) -> str | None:
        return self.active_chat_id

    def session_state(self) -> dict[str, object]:
        return {"ok": True, "conversation": []}


class TerminalWebSocketTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.policy = ExecutionPolicyService(root / "policy.db")
        self.broker = TerminalBroker(self.policy, receipts=TerminalReceiptStore(root / "receipts.db"))
        self.addCleanup(self.broker.shutdown)
        self.app = _App(self.broker)
        self.server = _LocalWebServer(("127.0.0.1", 0), _handler_for(self.app))
        self.app.port = self.server.server_port
        self.addCleanup(self.server.server_close)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.shutdown)
        self.host = f"127.0.0.1:{self.server.server_port}"
        self.origin = f"http://{self.host}"
        self.owner, self.cookie = self.app.terminal_browser_sessions.new()

    def launch(self, command: str) -> str:
        request = ExecutionRequest.create(command, self.temp.name, ExecutionScope.HOST_USER)
        grant = self.policy.issue_grant(request, "conversation", approved=True)
        return self.broker.launch(request, grant_token=grant.token,
                                  grant_owner="conversation", browser_owner=self.owner,
                                  authority=TerminalLocalAuthority.from_local_web(
                                      browser_owner=self.owner, client_address=("127.0.0.1", 12345),
                                      origin=RequestOrigin.local_web()),
                                  conversation_id="chat-a", turn_id="turn-a")

    def http(self, method: str, path: str, *, cookie: str | None = None,
             document: dict[str, object] | None = None) -> tuple[int, dict[str, object]]:
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        headers = {"Host": self.host, "Origin": self.origin, "X-Tori-CSRF": self.app.csrf_token}
        if cookie:
            headers["Cookie"] = cookie.split(";", 1)[0]
        if document is not None:
            headers["Content-Type"] = "application/json"
        connection.request(method, path, body=None if document is None else json.dumps(document), headers=headers)
        response = connection.getresponse()
        result = response.status, json.loads(response.read())
        connection.close()
        return result

    def connect(self, identifier: str, *, cookie: str | None = None,
                origin: str | None = None) -> tuple[socket.socket, object, bytes]:
        sock = socket.create_connection(("127.0.0.1", self.server.server_port), timeout=3)
        sock.settimeout(3)
        key = base64.b64encode(secrets.token_bytes(16)).decode()
        request = (f"GET /api/terminal/ws/{identifier} HTTP/1.1\r\nHost: {self.host}\r\n"
                   f"Origin: {self.origin if origin is None else origin}\r\n"
                   "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                   f"Sec-WebSocket-Version: 13\r\nSec-WebSocket-Key: {key}\r\n"
                   f"Cookie: {(self.cookie if cookie is None else cookie).split(';', 1)[0]}\r\n\r\n")
        sock.sendall(request.encode())
        stream = sock.makefile("rb")
        status = stream.readline()
        while stream.readline() != b"\r\n":
            pass
        return sock, stream, status

    def test_owner_ticket_websocket_and_reconnect(self) -> None:
        identifier = self.launch("/bin/sleep 3")
        second_owner, second_cookie = self.app.terminal_browser_sessions.new()
        self.assertNotEqual(second_owner, self.owner)
        self.assertEqual(self.http("GET", "/api/terminal/sessions", cookie=second_cookie)[1]["sessions"], [])
        self.assertEqual(self.http("POST", "/api/terminal/attach-ticket", cookie=second_cookie,
                                   document={"session_id": identifier})[0], 403)
        self.assertEqual(self.http("POST", "/api/terminal/attach-ticket", document={"session_id": identifier})[0], 403)
        status, body = self.http("POST", "/api/terminal/attach-ticket", cookie=self.cookie,
                                 document={"session_id": identifier})
        self.assertEqual(status, 200)
        ticket = body["ticket"]
        bad, _, bad_status = self.connect(identifier, cookie=second_cookie)
        self.assertIn(b"403", bad_status)
        bad.close()
        bad, _, bad_status = self.connect(identifier, origin="http://evil.example")
        self.assertIn(b"403", bad_status)
        bad.close()
        sock, stream, status_line = self.connect(identifier)
        self.assertTrue(status_line.startswith(b"HTTP/1.1 101"))
        sock.sendall(client_frame(1, json.dumps({"v": 1, "type": "attach", "ticket": ticket}).encode()))
        opcode, ready = read_server_frame(stream)
        self.assertEqual(opcode, 1)
        self.assertEqual(json.loads(ready)["type"], "ready")
        sock.close()
        time.sleep(.6)
        self.assertEqual(self.broker.list_sessions(self.owner)[0]["state"], "running")
        status, body = self.http("POST", "/api/terminal/attach-ticket", cookie=self.cookie,
                                 document={"session_id": identifier})
        self.assertEqual(status, 200)
        sock2, stream2, status_line2 = self.connect(identifier)
        self.assertIn(b"101", status_line2)
        sock2.sendall(client_frame(1, json.dumps({"v": 1, "type": "attach", "ticket": body["ticket"]}).encode()))
        self.assertEqual(json.loads(read_server_frame(stream2)[1])["type"], "ready")
        sock2.sendall(client_frame(1, b'{"v":1,"type":"take_control"}'))
        self.assertEqual(json.loads(read_server_frame(stream2)[1])["human_control"], True)
        sock2.close()
        self.assertNotIn(ticket, repr(self.broker._tickets))

    def test_no_output_before_attach_and_ticket_replay_fails(self) -> None:
        identifier = self.launch("/bin/echo secret-output")
        status, body = self.http("POST", "/api/terminal/attach-ticket", cookie=self.cookie,
                                 document={"session_id": identifier})
        self.assertEqual(status, 200)
        sock, stream, _ = self.connect(identifier)
        self.assertEqual(select.select([sock], [], [], .2)[0], [])
        sock.sendall(client_frame(1, json.dumps({"v": 1, "type": "attach", "ticket": body["ticket"]}).encode()))
        self.assertEqual(json.loads(read_server_frame(stream)[1])["type"], "ready")
        self.assertIn(b"secret-output", read_server_frame(stream)[1])
        sock.close()
        replay, replay_stream, _ = self.connect(identifier)
        replay.sendall(client_frame(1, json.dumps({"v": 1, "type": "attach", "ticket": body["ticket"]}).encode()))
        self.assertEqual(json.loads(read_server_frame(replay_stream)[1])["type"], "error")
        replay.close()

    def test_browser_input_requires_take_control_and_idle_attach_stays_live(self) -> None:
        identifier = self.launch("/bin/cat")
        _, body = self.http("POST", "/api/terminal/attach-ticket", cookie=self.cookie,
                            document={"session_id": identifier})
        sock, stream, _ = self.connect(identifier)
        sock.sendall(client_frame(1, json.dumps({"v": 1, "type": "attach", "ticket": body["ticket"]}).encode()))
        self.assertEqual(json.loads(read_server_frame(stream)[1])["type"], "ready")
        time.sleep(1.1)
        self.assertTrue(self.broker.list_sessions(self.owner)[0]["attached"])
        sock.sendall(client_frame(2, b"unapproved input"))
        self.assertEqual(json.loads(read_server_frame(stream)[1])["type"], "error")
        sock.close()
        self.assertEqual(self.broker.list_sessions(self.owner)[0]["state"], "running")

    def test_private_input_requires_control_and_survives_websocket_disconnect(self) -> None:
        identifier = self.launch("/bin/cat")
        _, body = self.http("POST", "/api/terminal/attach-ticket", cookie=self.cookie,
                            document={"session_id": identifier})
        sock, stream, _ = self.connect(identifier)
        sock.sendall(client_frame(1, json.dumps({"v": 1, "type": "attach", "ticket": body["ticket"]}).encode()))
        self.assertFalse(json.loads(read_server_frame(stream)[1])["session"]["private_input"])
        sock.sendall(client_frame(1, b'{"v":1,"type":"enter_private"}'))
        self.assertEqual(json.loads(read_server_frame(stream)[1])["type"], "error")
        sock.close()
        _, body = self.http("POST", "/api/terminal/attach-ticket", cookie=self.cookie,
                            document={"session_id": identifier})
        sock, stream, _ = self.connect(identifier)
        sock.sendall(client_frame(1, json.dumps({"v": 1, "type": "attach", "ticket": body["ticket"]}).encode()))
        read_server_frame(stream)
        sock.sendall(client_frame(1, b'{"v":1,"type":"take_control"}'))
        self.assertTrue(json.loads(read_server_frame(stream)[1])["human_control"])
        sock.sendall(client_frame(1, b'{"v":1,"type":"enter_private"}'))
        self.assertTrue(json.loads(read_server_frame(stream)[1])["private_input"])
        sock.close()
        time.sleep(.1)
        self.assertTrue(self.broker.list_sessions(self.owner)[0]["private_input"])
        _, body = self.http("POST", "/api/terminal/attach-ticket", cookie=self.cookie,
                            document={"session_id": identifier})
        reconnected, resumed, _ = self.connect(identifier)
        reconnected.sendall(client_frame(1, json.dumps({"v": 1, "type": "attach", "ticket": body["ticket"]}).encode()))
        ready = json.loads(read_server_frame(resumed)[1])
        self.assertTrue(ready["session"]["private_input"])
        self.assertFalse(ready["session"]["human_control"])
        reconnected.close()

    def test_no_browser_or_model_command_launch_route(self) -> None:
        status, _ = self.http("POST", "/api/terminal/launch", cookie=self.cookie,
                              document={"command": "/bin/sh -c id"})
        self.assertEqual(status, 404)
        self.assertEqual(self.broker.list_sessions(self.owner), [])

    def test_application_page_issues_browser_bound_cookie(self) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        connection.request("GET", "/", headers={"Host": self.host})
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        cookie = response.getheader("Set-Cookie")
        response.read()
        connection.close()
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertIn("Path=/", cookie)
        self.assertIsNotNone(self.app.terminal_browser_sessions.identify(cookie))
        self.assertEqual(self.app.terminal_browser_sessions.identify(
            "tori_terminal_session=old-slice2-cookie; " + cookie.split(";", 1)[0]),
            self.app.terminal_browser_sessions.identify(cookie))
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        connection.request("GET", "/", headers={"Host": self.host, "Cookie": cookie.split(";", 1)[0]})
        response = connection.getresponse()
        self.assertIsNone(response.getheader("Set-Cookie"))
        response.read()
        connection.close()

    def test_remote_peer_cannot_discover_ticket_or_attach_with_forged_headers(self) -> None:
        identifier = self.launch("/bin/sleep 3")
        with patch("tori.web.is_terminal_local_peer", return_value=False):
            self.assertFalse(self.http("GET", "/api/terminal/availability", cookie=self.cookie)[1]["available"])
            self.assertEqual(self.http("GET", "/api/terminal/sessions", cookie=self.cookie)[0], 403)
            self.assertEqual(self.http("POST", "/api/terminal/attach-ticket", cookie=self.cookie,
                                       document={"session_id": identifier})[0], 403)
            self.assertEqual(self.http("POST", "/api/terminal/request", cookie=self.cookie,
                                       document={"command": "/bin/echo remote", "cwd": self.temp.name,
                                                 "scope": "HOST_USER"})[0], 403)
            self.assertEqual(self.http("POST", "/api/terminal/decide", cookie=self.cookie,
                                       document={"proposal_token": "forged", "decision": "approve"})[0], 403)
            self.assertEqual(self.http("GET", "/api/session", cookie=self.cookie)[0], 200)
            connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
            connection.request("GET", "/", headers={"Host": self.host, "X-Forwarded-For": "127.0.0.1"})
            response = connection.getresponse()
            self.assertIsNone(response.getheader("Set-Cookie"))
            response.read()
            connection.close()
            sock, _, status = self.connect(identifier)
            self.assertIn(b"403", status)
            sock.close()
            self.assertEqual(self.http("POST", "/api/terminal/policy/create", cookie=self.cookie,
                                       document={"command": "/bin/echo hi", "cwd": self.temp.name,
                                                 "scope": "HOST_USER", "class": "WHITELIST",
                                                 "enabled": True})[0], 403)

    def test_local_browser_request_uses_policy_then_one_approval(self) -> None:
        status, proposed = self.http("POST", "/api/terminal/request", cookie=self.cookie,
                                     document={"command": "/bin/echo web-approved", "cwd": self.temp.name,
                                               "scope": "HOST_USER"})
        self.assertEqual(status, 200)
        self.assertEqual(proposed["policy"], "DEFAULT_ASK")
        self.assertNotIn("session_id", proposed)
        self.assertEqual(self.broker.list_sessions(self.owner), [])
        status, launched = self.http("POST", "/api/terminal/decide", cookie=self.cookie,
                                     document={"proposal_token": proposed["proposal_token"],
                                               "decision": "approve"})
        self.assertEqual(status, 200)
        self.assertTrue(self.broker.owns_session(launched["session_id"], self.owner))
        self.assertEqual(self.http("POST", "/api/terminal/decide", cookie=self.cookie,
                                    document={"proposal_token": proposed["proposal_token"],
                                              "decision": "approve"})[0], 409)

    def test_no_chat_manual_session_stays_owner_scoped_and_outside_chat(self) -> None:
        self.app.active_chat_id = None
        status, proposed = self.http("POST", "/api/terminal/request", cookie=self.cookie,
                                     document={"command": "pwd", "cwd": self.temp.name,
                                               "scope": "HOST_USER"})
        self.assertEqual(status, 200)
        self.assertEqual(proposed["policy"], "DEFAULT_ASK")
        other, other_cookie = self.app.terminal_browser_sessions.new()
        self.assertNotEqual(other, self.owner)
        self.assertEqual(self.http("GET", "/api/terminal/sessions", cookie=other_cookie)[1]["sessions"], [])
        self.assertEqual(self.http("POST", "/api/terminal/decide", cookie=other_cookie,
                                   document={"proposal_token": proposed["proposal_token"],
                                             "decision": "approve"})[0], 409)
        status, launched = self.http("POST", "/api/terminal/decide", cookie=self.cookie,
                                     document={"proposal_token": proposed["proposal_token"],
                                               "decision": "approve"})
        self.assertEqual(status, 200)
        identifier = launched["session_id"]
        binding = self.app.terminal_browser_sessions.conversation_binding(self.owner, None)
        self.assertEqual(self.broker.list_sessions(self.owner)[0]["conversation_id"], binding)
        self.assertNotEqual(binding, self.app.terminal_browser_sessions.conversation_binding(other, None))
        self.assertIsNone(self.app.terminal_browser_sessions.conversation_binding("forged", None))
        self.assertEqual(self.http("GET", "/api/terminal/sessions", cookie=self.cookie)[1]["sessions"][0]["id"], identifier)
        self.assertEqual(self.http("POST", "/api/terminal/attach-ticket", cookie=other_cookie,
                                   document={"session_id": identifier})[0], 403)
        self.assertEqual(self.http("GET", "/api/terminal/results/" + identifier,
                                   cookie=self.cookie)[0], 403)
        status, ticket = self.http("POST", "/api/terminal/attach-ticket", cookie=self.cookie,
                                   document={"session_id": identifier})
        self.assertEqual(status, 200)
        sock, stream, status_line = self.connect(identifier)
        self.assertIn(b"101", status_line)
        sock.sendall(client_frame(1, json.dumps({"v": 1, "type": "attach", "ticket": ticket["ticket"]}).encode()))
        self.assertEqual(json.loads(read_server_frame(stream)[1])["type"], "ready")
        sock.close()
        # A later real active chat cannot adopt a manually bound no-chat session.
        self.app.active_chat_id = "chat-a"
        self.assertEqual(self.http("GET", "/api/terminal/sessions", cookie=self.cookie)[1]["sessions"], [])
        self.assertEqual(self.http("POST", "/api/terminal/attach-ticket", cookie=self.cookie,
                                   document={"session_id": identifier})[0], 403)

    def test_policy_management_is_local_owner_bound_csrf_protected_and_exact(self) -> None:
        payload = {"command": "/bin/echo exact", "cwd": self.temp.name,
                   "scope": "HOST_USER", "class": "WHITELIST", "enabled": True}
        self.assertEqual(self.http("GET", "/api/terminal/policy")[0], 403)
        self.assertEqual(self.http("POST", "/api/terminal/policy/create", cookie=self.cookie,
                                   document=payload)[0], 200)
        status, listing = self.http("GET", "/api/terminal/policy", cookie=self.cookie)
        self.assertEqual(status, 200)
        self.assertEqual(listing["default"], "DEFAULT_ASK")
        rule = next(item for item in listing["rules"] if item["matcher"]["command"] == payload["command"])
        self.assertEqual(rule["class"], "WHITELIST")
        self.assertEqual(self.http("POST", "/api/terminal/policy/update", cookie=self.cookie,
                                   document={"id": rule["id"], **payload, "class": "BLACKLIST"})[0], 200)
        self.assertEqual(self.http("POST", "/api/terminal/policy/remove", cookie=self.cookie,
                                   document={"id": rule["id"]})[0], 200)
        high_risk = {**payload, "command": "sudo /bin/echo hi"}
        self.assertEqual(self.http("POST", "/api/terminal/policy/create", cookie=self.cookie,
                                   document=high_risk)[0], 409)
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        connection.request("POST", "/api/terminal/policy/create", body=json.dumps(payload),
                           headers={"Host": self.host, "Origin": self.origin,
                                    "Cookie": self.cookie.split(";", 1)[0],
                                    "Content-Type": "application/json"})
        response = connection.getresponse()
        self.assertEqual(response.status, 403)
        response.read()
        connection.close()

    def test_conversation_switch_hides_result_and_prevents_new_attachment(self) -> None:
        identifier = self.launch("/bin/echo bound")
        for _ in range(100):
            if self.broker.list_sessions(self.owner)[0]["state"] == "exited":
                break
            time.sleep(.02)
        status, result = self.http("GET", "/api/terminal/results/" + identifier, cookie=self.cookie)
        self.assertEqual(status, 200)
        self.assertEqual(result["result"]["classification"], "untrusted_execution_output")
        self.assertIn("bound", result["result"]["output"])
        self.app.active_chat_id = "chat-b"
        self.assertEqual(self.http("GET", "/api/terminal/sessions", cookie=self.cookie)[1]["sessions"], [])
        self.assertEqual(self.http("GET", "/api/terminal/results/" + identifier, cookie=self.cookie)[0], 403)
        self.assertEqual(self.http("POST", "/api/terminal/attach-ticket", cookie=self.cookie,
                                   document={"session_id": identifier})[0], 403)


if __name__ == "__main__":
    unittest.main()
