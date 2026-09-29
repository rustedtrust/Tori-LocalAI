#!/usr/bin/env python3
"""Disposable, native-host PROJECT_SANDBOX PTY acceptance probe.

Run from the repository root: .venv/bin/python scripts/validate-terminal-pty-host.py
Exit 2 means namespaces are unavailable in the current execution context.
All state is created beneath one TemporaryDirectory; canonical runtime is read-only.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tori.coding_work import CodingWorkAuthority  # noqa: E402
from tori.coding_work_supervisor import BubblewrapCodingWorkSandbox  # noqa: E402
from tori.execution_policy import ExecutionPolicyService, ExecutionRequest, ExecutionScope  # noqa: E402
from tori.request_origin import RequestOrigin  # noqa: E402
from tori.terminal_authority import TerminalLocalAuthority  # noqa: E402
from tori.terminal_broker import TerminalBroker  # noqa: E402
from tori.terminal_receipts import TerminalReceiptStore  # noqa: E402


PROBE = '''import json, os, signal, subprocess, sys, termios, time, fcntl, struct
def report(label, **fields):
    print("TORI_PTY_PROBE:" + json.dumps(dict(label=label, **fields), sort_keys=True), flush=True)
rows, cols, _, _ = struct.unpack("HHHH", fcntl.ioctl(0, termios.TIOCGWINSZ, bytes(8)))
report("ready", tty=os.isatty(0), foreground=os.tcgetpgrp(0)==os.getpgrp(),
       rows=rows, cols=cols, outside=os.path.exists("/workspaces"),
       runtime=os.path.exists("/workspace/runtime/protected"),
       secret="TORI_PROBE_SECRET" in os.environ)
line = sys.stdin.readline().strip()
report("input", line=line)
rows, cols, _, _ = struct.unpack("HHHH", fcntl.ioctl(0, termios.TIOCGWINSZ, bytes(8)))
report("resized", rows=rows, cols=cols)
child = subprocess.Popen(["/bin/sleep", "30"])
report("child", pid=child.pid, pgid=os.getpgid(child.pid))
def interrupted(signum, frame):
    report("interrupt", signum=signum)
    raise SystemExit(42)
signal.signal(signal.SIGINT, interrupted)
while True: time.sleep(.1)
'''


def wait_for(broker: TerminalBroker, owner: str, session_id: str,
             marker: bytes, timeout: float = 8) -> bytes:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with broker._lock:  # Test-only inspection; never written durably.
            output = bytes(broker._sessions[session_id].scrollback)
        if marker in output:
            return output
        time.sleep(.02)
    raise AssertionError(f"PTY probe did not reach {marker!r}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="tori-terminal-pty-host-") as directory:
        root = Path(directory)
        workspace = root / "workspace"
        workspace.mkdir()
        (workspace / "runtime").mkdir()
        (workspace / "runtime" / "protected").write_text("private", encoding="utf-8")
        (root / "outside").write_text("private", encoding="utf-8")
        (workspace / "probe.py").write_text(PROBE, encoding="utf-8")
        sandbox = BubblewrapCodingWorkSandbox(
            "/usr/bin/bwrap", protected_runtime_root=workspace / "runtime",
            project_collection_root=root / "collection")
        authority = CodingWorkAuthority(str(workspace), True, True, True)
        availability = sandbox.availability(authority)
        if not availability.available:
            print("ENVIRONMENT-BLOCKED: native Bubblewrap namespaces unavailable in this process")
            return 2
        policy = ExecutionPolicyService(root / "policy.db")
        broker = TerminalBroker(policy, sandbox=sandbox,
                                receipts=TerminalReceiptStore(root / "receipts.db"))
        owner = "host-acceptance-browser-owner-1234567890"
        local_authority = TerminalLocalAuthority.from_local_web(
            browser_owner=owner, client_address=("127.0.0.1", 1),
            origin=RequestOrigin.local_web())
        try:
            request = ExecutionRequest.create(
                "/usr/bin/python3 /workspace/probe.py", workspace,
                ExecutionScope.PROJECT_SANDBOX)
            grant = policy.issue_grant(request, "host-acceptance", approved=True)
            with __import__("unittest.mock", fromlist=["patch"]).patch.dict(
                    os.environ, {"TORI_PROBE_SECRET": "not-for-child"}):
                session_id = broker.launch(
                    request, grant_token=grant.token, grant_owner="host-acceptance",
                    browser_owner=owner, authority=local_authority,
                    conversation_id="host-acceptance", turn_id="host-acceptance-turn")
            output = wait_for(broker, owner, session_id, b'"label": "ready"')
            assert b'"tty": true' in output and b'"foreground": true' in output, output
            assert b'"outside": false' in output and b'"runtime": false' in output, output
            assert b'"secret": false' in output, output
            ticket = broker.issue_attach_ticket(session_id, owner)
            attachment, _, _ = broker.attach(session_id, owner, ticket)
            broker.take_control(attachment)
            broker.resize(attachment, 35, 100)
            broker.human_input(attachment, b"human-pty-input\n")
            output = wait_for(broker, owner, session_id, b'"label": "child"')
            assert b'"line": "human-pty-input"' in output, output
            assert b'"rows": 35' in output and b'"cols": 100' in output, output
            broker.signal(attachment, "interrupt")
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                state = broker.list_sessions(owner)[0]
                if state["state"] == "exited":
                    break
                time.sleep(.02)
            interrupt_output = bytes(broker._sessions[session_id].scrollback)
            assert state["state"] == "exited", state
            assert b'"label": "interrupt"' in interrupt_output, (
                "SIGINT did not reach the foreground Python handler", state)
            assert state["exit_code"] in {42, -2}, state  # bwrap may itself die from SIGINT.
            assert broker._sessions[session_id].process.poll() is not None
            broker.detach(attachment)
            print("PASS: native PROJECT_SANDBOX PTY, foreground job control, human input, resize, SIGINT, isolation and reap")
            return 0
        finally:
            broker.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
