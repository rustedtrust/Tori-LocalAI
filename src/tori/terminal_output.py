"""Bounded plain-text evidence capture, separate from human PTY scrollback."""

from __future__ import annotations

import codecs
import re


MAX_RESULT_BYTES = 64 * 1024
HEAD_BYTES = 16 * 1024
OMISSION = b"\n[terminal output omitted: result exceeded 64 KiB]\n"
PRIVATE_OMISSION = "\n[private terminal activity and subsequent output withheld]\n"
TAIL_BYTES = MAX_RESULT_BYTES - HEAD_BYTES - len(OMISSION)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b((?:api[_-]?key|access[_-]?token|bearer|password|secret)\s*[:=]\s*)\S+"
)


class _PlainTerminalDecoder:
    """Incrementally discard ANSI control strings, including split OSC frames."""

    def __init__(self) -> None:
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._state = "text"

    def feed(self, data: bytes) -> str:
        result: list[str] = []
        for char in self._decoder.decode(data):
            state = self._state
            if state == "text":
                if char == "\x1b":
                    self._state = "escape"
                elif char == "\x9b":
                    self._state = "csi"
                elif char in {"\x9d", "\x90", "\x9e", "\x9f"}:
                    self._state = "string"
                elif char == "\r":
                    result.append("\n")
                elif char in {"\n", "\t"} or (char.isprintable() and char != "\x7f"):
                    result.append(char)
            elif state == "escape":
                if char == "[":
                    self._state = "csi"
                elif char in {"]", "P", "_", "^", "X"}:
                    self._state = "string"
                else:
                    self._state = "text"
            elif state == "csi":
                if "@" <= char <= "~":
                    self._state = "text"
            elif state == "string":
                if char == "\x07" or char == "\x9c":
                    self._state = "text"
                elif char == "\x1b":
                    self._state = "string_escape"
            elif state == "string_escape":
                self._state = "text" if char == "\\" else "string"
        return "".join(result)


class TerminalModelCapture:
    """At most 64 KiB of sanitized merged PTY evidence; no durable writes."""

    def __init__(self) -> None:
        self._decoder = _PlainTerminalDecoder()
        self._head = bytearray()
        self._tail = bytearray()
        self._total = 0
        self.private_intervals = 0
        self.model_capture_locked = False

    def feed(self, data: bytes, *, private: bool) -> None:
        if private or self.model_capture_locked:
            return
        self._append(self._decoder.feed(data).encode("utf-8"))

    def begin_private(self) -> None:
        self.private_intervals += 1
        if not self.model_capture_locked:
            self.model_capture_locked = True
            self._decoder = _PlainTerminalDecoder()
            self._append(PRIVATE_OMISSION.encode("utf-8"))

    def end_private(self) -> None:
        # The keyboard/UI state can end, but this process can echo a secret
        # arbitrarily later. No action may reopen model capture for it.
        pass

    def _append(self, data: bytes) -> None:
        self._total += len(data)
        remaining = HEAD_BYTES - len(self._head)
        if remaining > 0:
            self._head.extend(data[:remaining])
            data = data[remaining:]
        if data:
            self._tail.extend(data)
            if len(self._tail) > TAIL_BYTES:
                del self._tail[:len(self._tail) - TAIL_BYTES]

    def result(self) -> tuple[str, bool]:
        truncated = self._total > MAX_RESULT_BYTES - len(OMISSION)
        raw = bytes(self._head)
        if truncated:
            raw += OMISSION
        raw += bytes(self._tail)
        text = raw.decode("utf-8", errors="replace")
        return _SECRET_ASSIGNMENT.sub(r"\1[redacted]", text), truncated
