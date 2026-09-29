"""Admission, PTY lifecycle, ownership, and data-boundary regression tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import signal
import stat
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from tori.execution_policy import ExecutionPolicyService, ExecutionRequest, ExecutionScope, PolicyClass, PolicyError
from tori.coding_work_supervisor import CodingWorkSandboxPlan
from tori.terminal_broker import TerminalBroker, TerminalError, _command_argv
from tori.terminal_receipts import TerminalReceiptStore
from tori.terminal_authority import TerminalLocalAuthority
from tori.request_origin import RequestOrigin
from tori.terminal_authority import is_terminal_local_peer


OWNER_A = "A" * 40
OWNER_B = "B" * 40
LOCAL_AUTH = TerminalLocalAuthority.from_local_web(
    browser_owner=OWNER_A, client_address=("127.0.0.1", 12345),
    origin=RequestOrigin.local_web())


class TerminalBrokerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.policy = ExecutionPolicyService(self.root / "policy.db")
        self.receipts = TerminalReceiptStore(self.root / "receipts.db")
        self.broker = TerminalBroker(self.policy, receipts=self.receipts, scrollback_bytes=4096)
        self.addCleanup(self.broker.shutdown)

    def request(self, command: str, scope: ExecutionScope = ExecutionScope.HOST_USER) -> ExecutionRequest:
        return ExecutionRequest.create(command, self.root, scope)

    def launch(self, command: str, *, owner: str = OWNER_A, approved: bool = True) -> str:
        request = self.request(command)
        grant = self.policy.issue_grant(request, "conversation-1", approved=approved)
        return self.broker.launch(request, grant_token=grant.token,
                                  grant_owner="conversation-1", browser_owner=owner,
                                  authority=TerminalLocalAuthority.from_local_web(
                                      browser_owner=owner, client_address=("127.0.0.1", 12345),
                                      origin=RequestOrigin.local_web()),
                                  conversation_id="chat-a", turn_id="turn-a")

    def wait_exit(self, identifier: str, owner: str = OWNER_A) -> dict[str, object]:
        for _ in range(150):
            state = next(item for item in self.broker.list_sessions(owner) if item["id"] == identifier)
            if state["state"] == "exited":
                return state
            time.sleep(.02)
        self.fail("terminal process did not exit")

    def test_grant_required_and_changed_command_fails_closed(self) -> None:
        first = self.request("/bin/echo first")
        second = self.request("/bin/echo second")
        with self.assertRaises(TerminalError):
            self.broker.launch(first, grant_token="invalid", grant_owner="conversation-1", browser_owner=OWNER_A, authority=LOCAL_AUTH, conversation_id="chat-a", turn_id="turn-a")
        grant = self.policy.issue_grant(first, "conversation-1", approved=True)
        with self.assertRaises(TerminalError):
            self.broker.launch(second, grant_token=grant.token, grant_owner="conversation-1", browser_owner=OWNER_A, authority=LOCAL_AUTH, conversation_id="chat-a", turn_id="turn-a")
        self.assertEqual(self.broker.list_sessions(OWNER_A), [])

    def test_terminal_origin_is_separate_from_whitelist_policy(self) -> None:
        self.assertTrue(is_terminal_local_peer(("127.0.0.1", 1)))
        self.assertTrue(is_terminal_local_peer(("::1", 1, 0, 0)))
        for peer in (("192.168.1.4", 1), ("127.0.0.2", 1),
                     ("::ffff:127.0.0.1", 1), ("localhost", 1), None):
            self.assertFalse(is_terminal_local_peer(peer))
            with self.assertRaises(PermissionError):
                TerminalLocalAuthority.from_local_web(
                    browser_owner=OWNER_A, client_address=peer,
                    origin=RequestOrigin.local_web())
        with self.assertRaises(PermissionError):
            TerminalLocalAuthority.from_local_web(
                browser_owner=OWNER_A, client_address=("127.0.0.1", 1),
                origin=RequestOrigin.local_cli())
        with self.assertRaises(PermissionError):
            TerminalLocalAuthority.from_local_web(
                browser_owner=OWNER_A, client_address=("127.0.0.1", 1),
                origin=RequestOrigin.discord_remote(
                    connector_id="discord", external_message_id="m", external_actor_id="a",
                    external_conversation_id="c"))
        request = self.request("/bin/echo authorized")
        self.policy.create_rule(request, PolicyClass.WHITELIST)
        grant = self.policy.issue_grant(request, "conversation-1")
        with self.assertRaises(TerminalError):
            self.broker.launch(request, grant_token=grant.token,
                               grant_owner="conversation-1", browser_owner=OWNER_B,
                               authority=LOCAL_AUTH, conversation_id="chat-a", turn_id="turn-a")
        self.assertEqual(self.broker.list_sessions(OWNER_A), [])

    def test_process_centric_argv_and_explicit_shell_semantics(self) -> None:
        self.assertEqual(_command_argv(self.request("sudo apt install example")),
                         ("sudo", "apt", "install", "example"))
        shell = self.request("/bin/echo one; /bin/echo two")
        self.assertEqual(_command_argv(shell), ("/bin/sh", "-c", shell.command))
        inline = self.request("EXAMPLE=yes /bin/echo hello")
        self.assertEqual(_command_argv(inline), ("/bin/sh", "-c", inline.command))

    def test_structured_command_runs_exact_argv_and_reaps(self) -> None:
        identifier = self.launch("/bin/echo approved")
        self.assertEqual(self.wait_exit(identifier)["exit_code"], 0)
        self.assertEqual(tuple(self.broker._sessions[identifier].process.args),
                         ("/bin/echo", "approved"))
        ticket = self.broker.issue_attach_ticket(identifier, OWNER_A)
        attachment, output, _ = self.broker.attach(identifier, OWNER_A, ticket)
        self.assertEqual(output, b"approved\r\n")
        self.broker.detach(attachment)
        with self.assertRaises(ChildProcessError):
            os.waitpid(self.broker._sessions[identifier].process.pid, os.WNOHANG)

    def test_host_user_pty_keeps_host_uid_groups_mount_namespace_and_devices(self) -> None:
        probe = self.root / "host_probe.py"
        probe.write_text(
            "import json, os, stat\n"
            "device = '/dev/nvidiactl'\n"
            "print(json.dumps({'uid': os.geteuid(), 'gid': os.getegid(), "
            "'groups': os.getgroups(), 'mount_namespace': os.readlink('/proc/self/ns/mnt'), "
            "'gpu_device': (os.stat(device).st_rdev, stat.S_IMODE(os.stat(device).st_mode)) "
            "if os.path.exists(device) else None}))\n",
            encoding="utf-8",
        )
        identifier = self.launch("/usr/bin/python3 " + str(probe))
        state = self.wait_exit(identifier)
        self.assertEqual(state["scope"], "HOST_USER")
        self.assertEqual(state["exit_code"], 0)
        observed = json.loads(bytes(self.broker._sessions[identifier].scrollback).decode().strip())
        self.assertEqual(observed["uid"], os.geteuid())
        self.assertEqual(observed["gid"], os.getegid())
        self.assertEqual(observed["groups"], os.getgroups())
        self.assertEqual(observed["mount_namespace"], os.readlink("/proc/self/ns/mnt"))
        gpu = Path("/dev/nvidiactl")
        if gpu.exists():
            device = gpu.stat()
            self.assertTrue(stat.S_ISCHR(device.st_mode))
            self.assertEqual(observed["gpu_device"], [device.st_rdev, stat.S_IMODE(device.st_mode)])

    def test_request_thread_exit_does_not_hang_up_live_child(self) -> None:
        launched: list[str] = []
        thread = threading.Thread(target=lambda: launched.append(self.launch("/bin/sleep 20")))
        thread.start()
        thread.join(timeout=3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(launched), 1)
        time.sleep(.15)
        self.assertEqual(self.broker.list_sessions(OWNER_A)[0]["state"], "running")
        ticket = self.broker.issue_attach_ticket(launched[0], OWNER_A)
        attachment, _, _ = self.broker.attach(launched[0], OWNER_A, ticket)
        self.broker.signal(attachment, "terminate")
        self.wait_exit(launched[0])

    def test_attach_ticket_owner_session_expiry_replay_and_terminal_binding(self) -> None:
        first = self.launch("/bin/echo one")
        second = self.launch("/bin/echo two")
        self.wait_exit(first)
        self.wait_exit(second)
        token = self.broker.issue_attach_ticket(first, OWNER_A)
        self.assertNotIn(token, repr(self.broker._tickets))
        with self.assertRaises(TerminalError):
            self.broker.attach(first, OWNER_B, token)
        with self.assertRaises(TerminalError):
            self.broker.attach(second, OWNER_A, token)
        with self.assertRaises(TerminalError):
            self.broker.attach(first, OWNER_A, token)
        token = self.broker.issue_attach_ticket(first, OWNER_A)
        attachment, _, _ = self.broker.attach(first, OWNER_A, token)
        with self.assertRaises(TerminalError):
            self.broker.attach(first, OWNER_A, token)
        self.broker.detach(attachment)
        token = self.broker.issue_attach_ticket(first, OWNER_A)
        self.broker._tickets[self.broker._digest(token)].expires_at = 0
        with self.assertRaises(TerminalError):
            self.broker.attach(first, OWNER_A, token)
        self.assertEqual(self.broker.list_sessions(OWNER_B), [])

    def test_disconnect_reconnect_and_human_control(self) -> None:
        identifier = self.launch("/bin/cat")
        ticket = self.broker.issue_attach_ticket(identifier, OWNER_A)
        first, _, _ = self.broker.attach(identifier, OWNER_A, ticket)
        with self.assertRaises(TerminalError):
            self.broker.human_input(first, b"no")
        self.broker.take_control(first)
        self.broker.human_input(first, b"hello\n")
        self.broker.detach(first)
        self.assertEqual(self.broker.list_sessions(OWNER_A)[0]["state"], "running")
        with self.assertRaises(TerminalError):
            self.broker.human_input(first, b"no")
        fresh = self.broker.issue_attach_ticket(identifier, OWNER_A)
        second, _, _ = self.broker.attach(identifier, OWNER_A, fresh)
        self.assertFalse(second.controlling)
        self.broker.take_control(second)
        third_ticket = self.broker.issue_attach_ticket(identifier, OWNER_A)
        third, _, _ = self.broker.attach(identifier, OWNER_A, third_ticket)
        self.assertFalse(first.controlling)
        self.assertFalse(second.controlling)
        self.assertFalse(third.controlling)
        with self.assertRaises(TerminalError):
            self.broker.human_input(second, b"no")
        self.broker.signal(third, "force_kill")
        self.wait_exit(identifier)

    def test_private_input_survives_disconnect_and_never_enters_model_result(self) -> None:
        identifier = self.launch("/bin/cat")
        ticket = self.broker.issue_attach_ticket(identifier, OWNER_A)
        first, _, _ = self.broker.attach(identifier, OWNER_A, ticket)
        with self.assertRaises(TerminalError):
            self.broker.enter_private(first)
        self.broker.take_control(first)
        self.broker.human_input(first, b"public-before\n")
        for _ in range(100):
            if b"public-before" in self.broker._sessions[identifier].scrollback:
                break
            time.sleep(.02)
        self.broker.enter_private(first)
        secret = b"UNIQUE_FAKE_SECRET_947326"
        self.broker.human_input(first, secret + b"\n")
        for _ in range(100):
            if secret in self.broker._sessions[identifier].scrollback:
                break
            time.sleep(.02)
        self.assertIn(secret, self.broker._sessions[identifier].scrollback)
        self.broker.detach(first)
        self.assertTrue(self.broker.list_sessions(OWNER_A)[0]["private_input"])
        fresh = self.broker.issue_attach_ticket(identifier, OWNER_A)
        second, snapshot, state = self.broker.attach(identifier, OWNER_A, fresh)
        self.assertIn(secret, snapshot)  # Human viewport only.
        self.assertTrue(state["private_input"])
        self.assertFalse(second.controlling)
        with self.assertRaises(TerminalError):
            self.broker.exit_private(second)
        self.broker.take_control(second)
        self.broker.exit_private(second)
        self.broker.human_input(second, b"public-after\n")
        for _ in range(100):
            if b"public-after" in self.broker._sessions[identifier].scrollback:
                break
            time.sleep(.02)
        self.broker.enter_private(second)
        self.broker.human_input(second, b"SECOND_PRIVATE_SECRET_726493\n")
        for _ in range(100):
            if b"SECOND_PRIVATE_SECRET_726493" in self.broker._sessions[identifier].scrollback:
                break
            time.sleep(.02)
        self.broker.signal(second, "force_kill")
        self.wait_exit(identifier)
        result = self.broker.model_result(identifier, conversation_id="chat-a", browser_owner=OWNER_A)
        self.assertEqual(result["classification"], "untrusted_execution_output")
        self.assertIn("public-before", result["output"])
        self.assertNotIn("public-after", result["output"])
        self.assertTrue(result["model_capture_locked"])
        self.assertNotIn(secret.decode(), result["output"])
        self.assertNotIn("SECOND_PRIVATE_SECRET_726493", result["output"])
        self.assertEqual(result["private_interval_count"], 2)
        with self.assertRaises(TerminalError):
            self.broker.model_result(identifier, conversation_id="chat-b", browser_owner=OWNER_A)
        durable = (self.root / "receipts.db").read_bytes()
        self.assertNotIn(secret, durable)
        self.assertNotIn(b"SECOND_PRIVATE_SECRET_726493", durable)
        self.assertNotIn(b"public-before", durable)
        with sqlite3.connect(self.root / "receipts.db") as connection:
            self.assertEqual(connection.execute(
                "SELECT conversation_id,turn_id,private_interval_count FROM terminal_receipts WHERE session_id=?",
                (identifier,)).fetchone(), ("chat-a", "turn-a", 2))

    def test_delayed_private_secret_after_ui_exit_stays_out_of_model_capture(self) -> None:
        secret = ("DELAYED_FAKE_SECRET_" + secrets.token_hex(12)).encode()
        command = ("/bin/sh -c 'printf public-before; "
                   "read saved; read trigger; printf \"quoted:%s\" \"$saved\"; "
                   "printf \"%s\" \"$saved\" | tr \"a-z\" \"A-Z\"; "
                   "printf public-after'")
        identifier = self.launch(command)
        for _ in range(100):
            if b"public-before" in self.broker._sessions[identifier].scrollback:
                break
            time.sleep(.02)
        ticket = self.broker.issue_attach_ticket(identifier, OWNER_A)
        attachment, _, _ = self.broker.attach(identifier, OWNER_A, ticket)
        self.broker.take_control(attachment)
        self.broker.enter_private(attachment)
        self.broker.human_input(attachment, secret + b"\n")
        self.broker.exit_private(attachment)
        self.assertTrue(self.broker.session_state(attachment)["model_capture_locked"])
        self.broker.human_input(attachment, b"go\n")
        self.wait_exit(identifier)
        self.assertIn(secret, self.broker._sessions[identifier].scrollback)
        transformed = secret.decode().upper()
        self.assertIn(transformed.encode(), self.broker._sessions[identifier].scrollback)
        result = self.broker.model_result(identifier, conversation_id="chat-a", browser_owner=OWNER_A)
        self.assertIn("public-before", result["output"])
        self.assertNotIn(secret.decode(), result["output"])
        self.assertNotIn(transformed, result["output"])
        self.assertNotIn("quoted:", result["output"])
        self.assertNotIn("public-after", result["output"])
        self.assertTrue(result["model_capture_locked"])
        self.assertNotIn(secret, (self.root / "receipts.db").read_bytes())
        for path in self.root.rglob("*"):
            if path.is_file():
                self.assertNotIn(secret, path.read_bytes(), str(path))
        second = self.launch("/bin/echo new-capture")
        self.wait_exit(second)
        fresh = self.broker.model_result(second, conversation_id="chat-a", browser_owner=OWNER_A)
        self.assertFalse(fresh["model_capture_locked"])
        self.assertIn("new-capture", fresh["output"])

    def test_v1_receipts_migrate_in_place_without_claiming_conversation_authority(self) -> None:
        legacy = self.root / "legacy-receipts.db"
        with sqlite3.connect(legacy) as connection:
            connection.execute("CREATE TABLE receipt_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            connection.execute("INSERT INTO receipt_metadata VALUES ('schema_version','1')")
            connection.execute("""CREATE TABLE terminal_receipts (
                session_id TEXT PRIMARY KEY, request_digest TEXT NOT NULL,
                owner_digest TEXT NOT NULL, grant_digest TEXT NOT NULL,
                scope TEXT NOT NULL, cwd TEXT NOT NULL, started_at REAL NOT NULL,
                ended_at REAL, exit_code INTEGER, termination_reason TEXT,
                state TEXT NOT NULL CHECK(state IN ('starting','running','exited','failed','interrupted'))
            )""")
            connection.execute("""INSERT INTO terminal_receipts VALUES
                ('term-legacy','digest','owner','grant','HOST_USER','/tmp',1,2,0,NULL,'exited')""")
        store = TerminalReceiptStore(legacy)
        store.reconcile_restart(3)
        with sqlite3.connect(legacy) as connection:
            self.assertEqual(connection.execute("SELECT value FROM receipt_metadata").fetchone(), ("2",))
            self.assertEqual(connection.execute("""SELECT conversation_id,turn_id,private_interval_count
                FROM terminal_receipts WHERE session_id='term-legacy'""").fetchone(),
                ("legacy-unbound", "legacy-unbound", 0))
            self.assertEqual(connection.execute("PRAGMA quick_check").fetchone(), ("ok",))

    def test_resize_environment_output_bound_and_receipts(self) -> None:
        os.environ["TORI_FAKE_CLOUD_SECRET"] = "must-not-inherit"
        self.addCleanup(os.environ.pop, "TORI_FAKE_CLOUD_SECRET", None)
        identifier = self.launch("/usr/bin/env")
        self.wait_exit(identifier)
        token = self.broker.issue_attach_ticket(identifier, OWNER_A)
        attachment, output, _ = self.broker.attach(identifier, OWNER_A, token)
        self.assertNotIn(b"must-not-inherit", output)
        self.assertNotIn(b"TORI_FAKE_CLOUD_SECRET", output)
        self.broker.detach(attachment)
        data = (self.root / "receipts.db").read_bytes()
        self.assertNotIn(b"TORI_FAKE_CLOUD_SECRET", data)
        self.assertNotIn(b"PATH=", data)
        self.assertIn(identifier.encode(), data)

        resizable = self.launch("/bin/sleep 20")
        ticket = self.broker.issue_attach_ticket(resizable, OWNER_A)
        attached, _, _ = self.broker.attach(resizable, OWNER_A, ticket)
        with self.assertRaises(TerminalError):
            self.broker.resize(attached, 0, 100)
        self.broker.resize(attached, 40, 120)
        self.broker.signal(attached, "force_kill")
        state = self.wait_exit(resizable)
        self.assertEqual(state["exit_code"], -signal.SIGKILL)
        self.assertEqual(state["termination_reason"], "force_kill")

        large = self.launch("/usr/bin/yes")
        for _ in range(200):
            if next(item for item in self.broker.list_sessions(OWNER_A)
                    if item["id"] == large)["scrollback_truncated"]:
                break
            time.sleep(.01)
        self.assertTrue(self.broker._sessions[large].truncated)
        self.assertLessEqual(len(self.broker._sessions[large].scrollback), 4096)
        ticket = self.broker.issue_attach_ticket(large, OWNER_A)
        attached, snapshot, _ = self.broker.attach(large, OWNER_A, ticket)
        self.assertLessEqual(len(snapshot), 4096)
        self.broker.detach(attached)
        self.broker.shutdown()
        self.assertEqual(self.wait_exit(large)["termination_reason"], "backend_shutdown")
        with sqlite3.connect(self.root / "receipts.db") as connection:
            self.assertEqual(connection.execute(
                "SELECT state,termination_reason FROM terminal_receipts WHERE session_id=?",
                (large,)).fetchone(), ("exited", "backend_shutdown"))

    def test_slow_output_attachment_disconnects_without_exiting_process(self) -> None:
        identifier = self.launch("/usr/bin/yes")
        ticket = self.broker.issue_attach_ticket(identifier, OWNER_A)
        attached, _, _ = self.broker.attach(identifier, OWNER_A, ticket)
        for _ in range(200):
            if not attached.active:
                break
            time.sleep(.01)
        self.assertFalse(attached.active)
        self.assertEqual(attached.events.qsize(), attached.events.maxsize)
        self.assertEqual(self.broker.list_sessions(OWNER_A)[0]["state"], "running")
        self.assertIsNone(self.broker._sessions[identifier].process.poll())
        with self.assertRaisesRegex(TerminalError, "attachment is no longer active"):
            self.broker.signal(attached, "force_kill")
        fresh = self.broker.issue_attach_ticket(identifier, OWNER_A)
        replacement, snapshot, state = self.broker.attach(identifier, OWNER_A, fresh)
        self.assertEqual(state["state"], "running")
        self.assertLessEqual(len(snapshot), 4096)
        self.broker.detach(replacement)
        self.broker.shutdown()
        self.assertEqual(self.wait_exit(identifier)["termination_reason"], "backend_shutdown")

    def test_interrupt_terminate_kill_and_shutdown(self) -> None:
        for operation in ("interrupt", "terminate", "force_kill"):
            identifier = self.launch("/bin/sleep 20")
            ticket = self.broker.issue_attach_ticket(identifier, OWNER_A)
            attachment, _, _ = self.broker.attach(identifier, OWNER_A, ticket)
            self.broker.signal(attachment, operation)
            state = self.wait_exit(identifier)
            self.assertEqual(state["termination_reason"], operation)
            self.assertEqual(state["exit_code"], -{"interrupt": signal.SIGINT, "terminate": signal.SIGTERM, "force_kill": signal.SIGKILL}[operation])
        identifier = self.launch("/bin/sleep 20")
        self.broker.shutdown()
        self.assertEqual(self.wait_exit(identifier)["termination_reason"], "backend_shutdown")

    def test_terminate_reaches_child_process_group(self) -> None:
        script = self.root / "parent.py"
        child_pid = self.root / "child.pid"
        script.write_text("import subprocess,sys,time\n"
                          "child=subprocess.Popen(['/bin/sleep','20'])\n"
                          "open(sys.argv[1],'w').write(str(child.pid))\n"
                          "child.wait()\n")
        identifier = self.launch(f"{sys.executable} {script} {child_pid}")
        for _ in range(100):
            if child_pid.exists():
                break
            time.sleep(.02)
        self.assertTrue(child_pid.exists())
        pid = int(child_pid.read_text())
        ticket = self.broker.issue_attach_ticket(identifier, OWNER_A)
        attachment, _, _ = self.broker.attach(identifier, OWNER_A, ticket)
        self.broker.signal(attachment, "terminate")
        self.wait_exit(identifier)
        for _ in range(100):
            try:
                state = Path(f"/proc/{pid}/stat").read_text().split()[2]
            except FileNotFoundError:
                break
            if state == "Z":
                break
            time.sleep(.02)
        else:
            self.fail("grandchild remains running after process-group termination")

    def test_interrupt_resistant_process_requires_termination(self) -> None:
        script = self.root / "ignore_int.py"
        script.write_text("import signal,time\n"
                          "signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
                          "print('ready', flush=True)\n"
                          "time.sleep(20)\n")
        identifier = self.launch(f"{sys.executable} {script}")
        ticket = self.broker.issue_attach_ticket(identifier, OWNER_A)
        attachment, _, _ = self.broker.attach(identifier, OWNER_A, ticket)
        for _ in range(100):
            if b"ready" in self.broker._sessions[identifier].scrollback:
                break
            time.sleep(.02)
        self.assertIn(b"ready", self.broker._sessions[identifier].scrollback)
        self.broker.signal(attachment, "interrupt")
        time.sleep(.1)
        self.assertEqual(self.broker.list_sessions(OWNER_A)[0]["state"], "running")
        self.broker.signal(attachment, "terminate")
        self.assertEqual(self.wait_exit(identifier)["termination_reason"], "terminate")

    def test_receipts_reconcile_restart_without_pid_cleanup(self) -> None:
        self.receipts.start("term-old", "a" * 64, "b" * 64, "c" * 64,
                            "HOST_USER", str(self.root), 1.0, "chat-a", "turn-a")
        self.receipts.mark_running("term-old")
        self.receipts.reconcile_restart(2.0)
        with sqlite3.connect(self.root / "receipts.db") as connection:
            self.assertEqual(connection.execute("SELECT state,termination_reason FROM terminal_receipts WHERE session_id='term-old'").fetchone(),
                             ("interrupted", "backend_restart_unverified"))

    def test_project_scope_reuses_sandbox_plan_and_rejects_substitution(self) -> None:
        class Sandbox:
            def __init__(self, substitute: bool = False) -> None:
                self.substitute = substitute
                self.authority = None

            def plan(self, argv, authority):  # type: ignore[no-untyped-def]
                self.authority = authority
                command = ("/bin/echo", "substituted") if self.substitute else tuple(argv)
                return CodingWorkSandboxPlan(command, {}, str(self_root), "read_write", "absent", "outside_sandbox", "test")

        self_root = self.root
        sandbox = Sandbox()
        broker = TerminalBroker(self.policy, sandbox=sandbox, receipts=self.receipts)
        self.addCleanup(broker.shutdown)
        request = self.request("/bin/echo approved", ExecutionScope.PROJECT_SANDBOX)
        grant = self.policy.issue_grant(request, "conversation", approved=True)
        identifier = broker.launch(request, grant_token=grant.token, grant_owner="conversation", browser_owner=OWNER_A, authority=LOCAL_AUTH, conversation_id="chat-a", turn_id="turn-a")
        self.assertTrue(sandbox.authority.sandboxed_execution_allowed)
        for _ in range(100):
            if broker.list_sessions(OWNER_A)[0]["state"] == "exited":
                break
            time.sleep(.02)
        token = broker.issue_attach_ticket(identifier, OWNER_A)
        attached, output, _ = broker.attach(identifier, OWNER_A, token)
        self.assertEqual(output, b"approved\r\n")
        broker.detach(attached)
        altered = Sandbox(substitute=True)
        wrong = TerminalBroker(self.policy, sandbox=altered, receipts=self.receipts)
        self.addCleanup(wrong.shutdown)
        another = self.policy.issue_grant(request, "conversation", approved=True)
        with self.assertRaises(TerminalError):
            wrong.launch(request, grant_token=another.token, grant_owner="conversation", browser_owner=OWNER_A, authority=LOCAL_AUTH, conversation_id="chat-a", turn_id="turn-a")

    def test_spawn_and_pty_failures_are_receipted(self) -> None:
        with self.assertRaises(PolicyError):
            ExecutionRequest.create("/bin/echo", self.root / "missing-cwd", ExecutionScope.HOST_USER)
        with patch("tori.terminal_broker.os.openpty", side_effect=OSError("fake")):
            with self.assertRaises(TerminalError):
                self.launch("/bin/echo failure")
        with self.assertRaises(TerminalError):
            self.launch(str(self.root / "missing-executable"))
        path = self.root / "not-executable"
        path.write_text("data")
        with self.assertRaises(TerminalError):
            self.launch(str(path))
        self.assertEqual(self.broker.list_sessions(OWNER_A), [])

    def test_unavailable_audit_store_prevents_launch(self) -> None:
        target = self.root / "other-file"
        target.write_text("untouched")
        link = self.root / "receipt-link"
        link.symlink_to(target)
        broker = TerminalBroker(self.policy, receipts=TerminalReceiptStore(link))
        self.addCleanup(broker.shutdown)
        request = self.request("/bin/echo should-not-run")
        grant = self.policy.issue_grant(request, "conversation", approved=True)
        with self.assertRaises(TerminalError):
            broker.launch(request, grant_token=grant.token,
                          grant_owner="conversation", browser_owner=OWNER_A, authority=LOCAL_AUTH,
                          conversation_id="chat-a", turn_id="turn-a")
        self.assertEqual(target.read_text(), "untouched")
        self.assertEqual(broker.list_sessions(OWNER_A), [])


if __name__ == "__main__":
    unittest.main()
