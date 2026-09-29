"""Small RFC 6455 transport for the terminal broker on Tori's existing port."""

from __future__ import annotations

import base64
import hashlib
import json
import queue
import re
import select
import secrets
import socket
import struct
import threading
from http.cookies import SimpleCookie

from .terminal_broker import TerminalAttachment, TerminalBroker, TerminalError, MAX_FRAME_BYTES


_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class WebSocketError(RuntimeError):
    pass


class TerminalBrowserSessions:
    """Ephemeral browser isolation within Tori's existing LAN access boundary.

    Tori has no account login. This cookie is a browser-session binding, not
    proof of a named human identity. Only its digest is retained server-side.
    """

    # New name avoids duplicate old Path=/api/terminal cookies during the
    # Slice 2 -> 3 path migration. Old cookies confer no authority here.
    COOKIE_NAME = "tori_terminal_local_session"

    def __init__(self) -> None:
        self._digests: set[str] = set()
        self._lock = threading.Lock()

    def new(self) -> tuple[str, str]:
        token = secrets.token_urlsafe(32)
        with self._lock:
            if len(self._digests) >= 2048:
                raise WebSocketError("Too many browser sessions.")
            self._digests.add(hashlib.sha256(token.encode()).hexdigest())
        # The page itself must receive this cookie on reload so it can keep
        # the same owner. A narrower /api/terminal path silently reissued a
        # new owner on every GET /, breaking reconnect.
        return token, f"{self.COOKIE_NAME}={token}; HttpOnly; SameSite=Strict; Path=/"

    def identify(self, raw_cookie: str | None) -> str | None:
        if not raw_cookie or len(raw_cookie) > 4096:
            return None
        if len(re.findall(r"(?:^|;\s*)" + self.COOKIE_NAME + r"=", raw_cookie)) != 1:
            return None
        cookie = SimpleCookie()
        try:
            cookie.load(raw_cookie)
        except Exception:
            return None
        morsel = cookie.get(self.COOKIE_NAME)
        if morsel is None:
            return None
        token = morsel.value
        if re.fullmatch(r"[A-Za-z0-9_-]{43}", token) is None:
            return None
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self._lock:
            return token if digest in self._digests else None

    def conversation_binding(self, owner: str | None, active_chat_id: str | None) -> str | None:
        """Bind a local owner's manual PTY to the current chat or a private no-chat scope.

        The no-chat scope is process-local and never becomes an archive chat or
        model-result origin. A fresh browser owner gets a different scope.
        """
        if not isinstance(owner, str):
            return None
        digest = hashlib.sha256(owner.encode()).hexdigest()
        with self._lock:
            if digest not in self._digests:
                return None
        return active_chat_id if active_chat_id is not None else "manual-terminal-" + digest


def _read_exact(stream: object, count: int) -> bytes:
    data = bytearray()
    while len(data) < count:
        chunk = stream.read(count - len(data))  # type: ignore[attr-defined]
        if not chunk:
            raise WebSocketError("Connection closed.")
        data.extend(chunk)
    return bytes(data)


def _read_frame(stream: object) -> tuple[int, bytes]:
    header = _read_exact(stream, 2)
    if header[0] & 0x70 or not header[0] & 0x80 or not header[1] & 0x80:
        raise WebSocketError("Invalid client frame.")
    opcode = header[0] & 15
    if opcode not in {1, 2, 8, 9, 10}:
        raise WebSocketError("Unsupported frame.")
    length = header[1] & 127
    if length == 126:
        length = struct.unpack("!H", _read_exact(stream, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _read_exact(stream, 8))[0]
    if length > MAX_FRAME_BYTES or (opcode >= 8 and length > 125):
        raise WebSocketError("Frame too large.")
    mask = _read_exact(stream, 4)
    payload = _read_exact(stream, length)
    return opcode, bytes(value ^ mask[i % 4] for i, value in enumerate(payload))


def _frame(opcode: int, payload: bytes) -> bytes:
    length = len(payload)
    if length < 126:
        header = bytes((0x80 | opcode, length))
    elif length < 65536:
        header = bytes((0x80 | opcode, 126)) + struct.pack("!H", length)
    else:
        header = bytes((0x80 | opcode, 127)) + struct.pack("!Q", length)
    return header + payload


def _json_frame(document: dict[str, object]) -> bytes:
    return _frame(1, json.dumps(document, separators=(",", ":")).encode("utf-8"))


def serve_terminal_websocket(handler: object, broker: TerminalBroker, session_id: str,
                             owner: str) -> None:
    """Upgrade only after Host/Origin/cookie gates in the HTTP handler."""
    headers = handler.headers  # type: ignore[attr-defined]
    if (headers.get("Upgrade", "").lower() != "websocket" or
            "upgrade" not in {part.strip() for part in headers.get("Connection", "").lower().split(",")} or
            headers.get("Sec-WebSocket-Version") != "13"):
        raise WebSocketError("Invalid WebSocket upgrade.")
    keys = headers.get_all("Sec-WebSocket-Key", failobj=[])
    try:
        key_bytes = base64.b64decode(keys[0], validate=True) if len(keys) == 1 else b""
    except (ValueError, base64.binascii.Error):
        key_bytes = b""
    if len(key_bytes) != 16:
        raise WebSocketError("Invalid WebSocket key.")
    accept = base64.b64encode(hashlib.sha1((keys[0] + _GUID).encode("ascii")).digest()).decode("ascii")
    handler.protocol_version = "HTTP/1.1"  # type: ignore[attr-defined]
    handler.send_response(101)  # type: ignore[attr-defined]
    handler.send_header("Upgrade", "websocket")  # type: ignore[attr-defined]
    handler.send_header("Connection", "Upgrade")  # type: ignore[attr-defined]
    handler.send_header("Sec-WebSocket-Accept", accept)  # type: ignore[attr-defined]
    handler.end_headers()  # type: ignore[attr-defined]
    handler.close_connection = True  # type: ignore[attr-defined]
    connection = handler.connection  # type: ignore[attr-defined]
    connection.settimeout(5)
    stream = connection.makefile("rb", buffering=0)
    attachment: TerminalAttachment | None = None
    write_lock = threading.Lock()
    sender_stop = threading.Event()

    def send(data: bytes) -> None:
        with write_lock:
            connection.sendall(data)

    try:
        opcode, raw = _read_frame(stream)
        if opcode != 1:
            raise WebSocketError("Attach must be the first message.")
        try:
            message = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WebSocketError("Invalid attach message.") from exc
        if (not isinstance(message, dict) or set(message) != {"v", "type", "ticket"}
                or message.get("v") != 1 or message.get("type") != "attach"):
            raise WebSocketError("Attach must be the first message.")
        attachment, snapshot, state = broker.attach(session_id, owner, message["ticket"])
        send(_json_frame({"v": 1, "type": "ready", "session": state}))
        if snapshot:
            # The binary snapshot is queued before live events by the broker lock.
            for offset in range(0, len(snapshot), MAX_FRAME_BYTES):
                send(_frame(2, snapshot[offset:offset + MAX_FRAME_BYTES]))
        if state["state"] == "exited":
            send(_json_frame({"v": 1, "type": "exit", "session": state}))

        def forward() -> None:
            assert attachment is not None
            while not sender_stop.is_set() and attachment.active:
                try:
                    kind, payload = attachment.events.get(timeout=0.5)
                except queue.Empty:
                    continue
                try:
                    if kind == "output":
                        send(_frame(2, payload))  # type: ignore[arg-type]
                    elif kind == "exit":
                        send(_json_frame({"v": 1, "type": "exit", "session": payload}))  # type: ignore[dict-item]
                    elif kind == "superseded":
                        send(_json_frame({"v": 1, "type": "superseded"}))
                        return
                except OSError:
                    return

        sender = threading.Thread(target=forward, daemon=True, name="tori-terminal-websocket-output")
        sender.start()
        while attachment.active:
            if not select.select([connection], [], [], 0.5)[0]:
                continue
            opcode, raw = _read_frame(stream)
            if opcode == 8:
                break
            if opcode == 9:
                send(_frame(10, raw))
                continue
            if opcode == 2:
                broker.human_input(attachment, raw)
                continue
            if opcode != 1:
                raise WebSocketError("Unexpected frame.")
            try:
                control = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise WebSocketError("Invalid control message.") from exc
            if not isinstance(control, dict) or control.get("v") != 1:
                raise WebSocketError("Invalid protocol version.")
            kind = control.get("type")
            if kind == "resize" and set(control) == {"v", "type", "rows", "columns"}:
                broker.resize(attachment, control["rows"], control["columns"])
            elif kind == "take_control" and set(control) == {"v", "type"}:
                broker.take_control(attachment)
            elif kind == "release_control" and set(control) == {"v", "type"}:
                broker.release_control(attachment)
            elif kind == "enter_private" and set(control) == {"v", "type"}:
                broker.enter_private(attachment)
            elif kind == "exit_private" and set(control) == {"v", "type"}:
                broker.exit_private(attachment)
            elif kind in {"interrupt", "terminate", "force_kill"} and set(control) == {"v", "type"}:
                broker.signal(attachment, kind)
            else:
                raise WebSocketError("Unknown control message.")
            state = broker.session_state(attachment)
            send(_json_frame({"v": 1, "type": "state", "human_control": attachment.controlling,
                              "private_input": state["private_input"],
                              "model_capture_locked": state["model_capture_locked"]}))
    except (WebSocketError, TerminalError, OSError, ValueError, TypeError):
        try:
            send(_json_frame({"v": 1, "type": "error", "code": "terminal_unavailable"}))
        except OSError:
            pass
    finally:
        sender_stop.set()
        if attachment is not None:
            broker.detach(attachment)
        stream.close()
        try:
            connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
