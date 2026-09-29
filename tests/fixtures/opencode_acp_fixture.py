#!/usr/bin/env python3
"""Deterministic OpenCode-shaped ACP subprocess for production-adapter tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import sys
import time


STATE = Path(sys.argv[1])
STATE.parent.mkdir(parents=True, exist_ok=True)


def send(document: dict[str, object]) -> None:
    print(json.dumps(document, separators=(",", ":")), flush=True)


def result(identifier: int, document: dict[str, object]) -> None:
    send({"jsonrpc": "2.0", "id": identifier, "result": document})


def update(kind: str, **values: object) -> None:
    send({
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {"update": {"sessionUpdate": kind, **values}},
    })


def sessions() -> dict[str, object]:
    if not STATE.exists():
        return {"next": 1, "sessions": {}, "prompt_count": 0}
    return json.loads(STATE.read_text(encoding="utf-8"))


def save(document: dict[str, object]) -> None:
    temporary = STATE.with_name(STATE.name + ".tmp")
    temporary.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
    temporary.replace(STATE)


def main() -> int:
    state = sessions()
    active: str | None = None
    for line in sys.stdin:
        request = json.loads(line)
        identifier = request.get("id")
        method = request.get("method")
        params = request.get("params", {})
        if not isinstance(identifier, int) or not isinstance(method, str):
            continue
        if method == "initialize":
            result(identifier, {"protocolVersion": 1})
        elif method == "session/new":
            active = f"ses_fixture_{state['next']}"
            state["next"] += 1
            state["sessions"][active] = {"prompts": []}
            save(state)
            result(identifier, {"sessionId": active})
        elif method == "session/load":
            candidate = params.get("sessionId")
            if candidate not in state["sessions"]:
                send({
                    "jsonrpc": "2.0", "id": identifier,
                    "error": {"code": -32000, "message": "missing"},
                })
            else:
                active = candidate
                result(identifier, {"sessionId": active})
        elif method == "session/prompt":
            if active is None:
                send({
                    "jsonrpc": "2.0", "id": identifier,
                    "error": {"code": -32000, "message": "missing"},
                })
                continue
            prompt = params["prompt"][0]["text"]
            state["sessions"][active]["prompts"].append(prompt)
            state["prompt_count"] += 1
            save(state)
            update("agent_thought_chunk", content={"text": "private reasoning"})
            update("usage_update", used=42)
            update("available_commands_update", commands=["noise"])
            if "BROADER_AUTHORITY" in prompt:
                send({
                    "jsonrpc": "2.0",
                    "id": 9000 + identifier,
                    "method": "session/request_permission",
                    "params": {
                        "permission": "external_directory",
                        "options": [
                            {"optionId": "deny", "kind": "reject_once"},
                            {"optionId": "allow", "kind": "allow_once"},
                        ],
                    },
                })
                json.loads(sys.stdin.readline())
            if "CRASH_PROCESS" in prompt:
                print("synthetic OpenCode crash", file=sys.stderr, flush=True)
                return 9
            if "SIGNAL_PROCESS" in prompt:
                os.kill(os.getpid(), signal.SIGKILL)
            if "SLEEP_UNTIL_CANCELLED" in prompt:
                time.sleep(30)
            Path("adapter-output.txt").write_text("changed\n", encoding="utf-8")
            update(
                "tool_call",
                title="Edit adapter-output.txt",
                locations=[{"path": "adapter-output.txt"}],
            )
            update(
                "tool_call_update",
                title="Edit adapter-output.txt",
                status="completed",
                locations=[{"path": "adapter-output.txt"}],
            )
            update("agent_message_chunk", content={"text": "Completed synthetic edit."})
            result(identifier, {"stopReason": "end_turn"})
        elif method == "session/close":
            result(identifier, {})
        else:
            send({
                "jsonrpc": "2.0", "id": identifier,
                "error": {"code": -32601, "message": "unknown"},
            })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
