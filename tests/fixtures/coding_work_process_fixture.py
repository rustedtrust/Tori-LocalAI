#!/usr/bin/env python3
"""Deterministic JSONL worker fixture for Coding Work supervisor tests."""

from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time


def emit(kind: str, payload: dict[str, object] | None = None) -> None:
    print(json.dumps({"kind": kind, "payload": payload or {}}, sort_keys=True), flush=True)


def evidence(summary: str, changed: list[str] | None = None) -> dict[str, object]:
    return {
        "summary": summary,
        "changed_paths": changed or [],
        "verification": [],
        "artifacts": [],
    }


def cancel_handler(_signum: int, _frame: object) -> None:
    emit("cancelled", {"evidence": evidence("The fixture was cancelled.")})
    raise SystemExit(0)


def delayed_cancel_handler(_signum: int, _frame: object) -> None:
    time.sleep(30)


def enable_parent_death_signal() -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "prctl(PR_SET_PDEATHSIG) failed")


def directive_loop() -> None:
    for line in sys.stdin:
        document = json.loads(line)
        if document["kind"] == "instruction":
            emit("session_confirmed", {"reason": "follow_up"})
            if document.get("instruction") == "EMIT_MANY":
                for index in range(600):
                    emit("progress", {
                        "summary": f"bounded progress {index}",
                        "changed_paths": [],
                        "verification": None,
                    })
                emit("waiting", {"reason": "bounded_history_fixture"})
                continue
            emit("progress", {
                "summary": "Applied follow-up instruction",
                "changed_paths": [],
                "verification": document["directive_id"],
            })
        elif document["kind"] == "cancel":
            cancel_handler(signal.SIGTERM, None)


def security_probe(arguments: list[str]) -> None:
    outside, runtime_secret, home_secret = map(Path, arguments)
    workspace_file = Path("fixture-written.txt")
    workspace_file.write_text("fixture-write\n", encoding="utf-8")
    try:
        (Path(".git") / "fixture-write").write_text("forbidden\n", encoding="utf-8")
        git_control_writable = True
    except OSError:
        git_control_writable = False
    try:
        connection = socket.create_connection(("1.1.1.1", 53), timeout=0.2)
    except OSError:
        network_available = False
    else:
        connection.close()
        network_available = True
    observations = {
        "workspace_read": Path("fixture-readable.txt").read_text(encoding="utf-8"),
        "git_head_readable": (Path(".git") / "HEAD").is_file(),
        "outside_visible": outside.exists(),
        "runtime_visible": runtime_secret.exists(),
        "home_secret_visible": home_secret.exists(),
        "symlink_escape_visible": Path("escape").exists(),
        "git_control_writable": git_control_writable,
        "network_available": network_available,
        "synthetic_secret": os.environ.get("TORI_SYNTHETIC_SECRET", "unset"),
        "home": os.environ.get("HOME", "unset"),
        "ssh_auth_sock": os.environ.get("SSH_AUTH_SOCK", "unset"),
        "docker_host": os.environ.get("DOCKER_HOST", "unset"),
    }
    emit("progress", {
        "summary": "Completed fixture security probes",
        "changed_paths": [str(workspace_file)],
        "verification": observations,
    })
    emit("completed", {
        "evidence": evidence("Fixture security probes completed.", [str(workspace_file)])
    })


def main() -> int:
    mode = sys.argv[1]
    signal.signal(signal.SIGTERM, cancel_handler)
    if mode == "parent-death-wait":
        enable_parent_death_signal()
    emit("session_confirmed")
    if mode == "complete":
        Path("fixture-output.txt").write_text("completed\n", encoding="utf-8")
        emit("progress", {
            "summary": "Fixture modified the workspace",
            "changed_paths": ["fixture-output.txt"],
            "verification": "not_run",
        })
        emit("completed", {
            "evidence": evidence("The fixture completed.", ["fixture-output.txt"])
        })
        return 0
    if mode == "crash":
        print("synthetic fixture crash " + "x" * 1_000, file=sys.stderr, flush=True)
        return 7
    if mode == "wait":
        emit("waiting", {"reason": "fixture_waiting"})
        directive_loop()
        return 0
    if mode == "parent-death-wait":
        emit("waiting", {"reason": "parent_death_fixture_waiting"})
        directive_loop()
        return 0
    if mode == "delay-cancel":
        signal.signal(signal.SIGTERM, delayed_cancel_handler)
        emit("waiting", {"reason": "fixture_delays_cancellation"})
        while True:
            time.sleep(1)
    if mode == "spawn-child":
        child = subprocess.Popen(["/bin/sh", "-c", "sleep 30"])
        emit("progress", {
            "summary": "Fixture spawned a child",
            "changed_paths": [],
            "verification": str(child.pid),
        })
        emit("completed", {"evidence": evidence("Fixture parent completed.")})
        return 0
    if mode == "security-probe":
        security_probe(sys.argv[2:5])
        return 0
    if mode == "project-dependency-artifacts":
        paths = [Path(".venv/fixture-package"), Path("node_modules/fixture/package.json")]
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture\n", encoding="utf-8")
        emit("completed", {
            "evidence": evidence(
                "Project-local dependency artifacts were ordinary workspace changes.",
                [str(path) for path in paths],
            )
        })
        return 0
    raise RuntimeError("unsupported fixture mode")


if __name__ == "__main__":
    raise SystemExit(main())
