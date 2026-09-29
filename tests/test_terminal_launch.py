"""Local browser execution origin is independent of command policy."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tori.execution_policy import ExecutionPolicyService, ExecutionRequest, ExecutionScope, PolicyClass
from tori.request_origin import RequestOrigin
from tori.terminal_authority import TerminalLocalAuthority
from tori.terminal_broker import TerminalBroker
from tori.terminal_launch import TerminalLaunchService, TerminalLaunchError
from tori.terminal_receipts import TerminalReceiptStore


OWNER = "local-browser-owner-12345678901234567890"
OTHER = "other-browser-owner-12345678901234567890"


class TerminalLaunchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.policy = ExecutionPolicyService(self.root / "policy.db")
        self.broker = TerminalBroker(self.policy, receipts=TerminalReceiptStore(self.root / "receipts.db"))
        self.addCleanup(self.broker.shutdown)
        self.launcher = TerminalLaunchService(self.policy, self.broker)
        self.authority = TerminalLocalAuthority.from_local_web(
            browser_owner=OWNER, client_address=("127.0.0.1", 9000),
            origin=RequestOrigin.local_web())

    def request(self, command: str, authority: TerminalLocalAuthority | None = None) -> dict[str, object]:
        return self.launcher.request(command, str(self.root), "HOST_USER",
                                     self.authority if authority is None else authority,
                                     conversation_id="chat-a", turn_id="turn-a")

    def decide(self, token: str, decision: str,
               authority: TerminalLocalAuthority | None = None) -> dict[str, object]:
        return self.launcher.decide(token, decision,
                                    self.authority if authority is None else authority,
                                    conversation_id="chat-a")

    def test_unknown_asks_once_and_proposal_is_owner_bound_and_single_use(self) -> None:
        proposal = self.request("/bin/echo approved")
        self.assertEqual(proposal["policy"], "DEFAULT_ASK")
        self.assertNotIn("session_id", proposal)
        self.assertEqual(self.broker.list_sessions(OWNER), [])
        other = TerminalLocalAuthority.from_local_web(
            browser_owner=OTHER, client_address=("::1", 9000),
            origin=RequestOrigin.local_web())
        with self.assertRaises(TerminalLaunchError):
            self.decide(proposal["proposal_token"], "approve", other)
        launched = self.decide(proposal["proposal_token"], "approve")
        self.assertTrue(self.broker.owns_session(launched["session_id"], OWNER))
        with self.assertRaises(TerminalLaunchError):
            self.decide(proposal["proposal_token"], "approve")
        self.assertNotIn(proposal["proposal_token"], repr(self.launcher._proposals))

    def test_whitelist_still_requires_local_origin_and_blacklist_cannot_run(self) -> None:
        request = ExecutionRequest.create("/bin/echo safe", self.root, ExecutionScope.HOST_USER)
        self.policy.create_rule(request, PolicyClass.WHITELIST)
        with self.assertRaises(TerminalLaunchError):
            self.launcher.request(request.command, str(self.root), "HOST_USER", None,
                                  conversation_id="chat-a", turn_id="turn-a")
        result = self.request(request.command)
        self.assertEqual(result["policy"], "WHITELIST")
        self.assertIn("session_id", result)
        self.assertNotIn("proposal_token", result)
        blocked = ExecutionRequest.create("/bin/echo blocked", self.root, ExecutionScope.HOST_USER)
        self.policy.create_rule(blocked, PolicyClass.BLACKLIST)
        denied = self.request(blocked.command)
        self.assertEqual(denied["policy"], "BLACKLIST")
        self.assertNotIn("session_id", denied)
        self.assertNotIn("proposal_token", denied)

    def test_always_ask_and_policy_change_are_rechecked_at_approval(self) -> None:
        request = ExecutionRequest.create("/bin/echo one", self.root, ExecutionScope.HOST_USER)
        self.policy.create_rule(request, PolicyClass.ALWAYS_ASK)
        proposed = self.request(request.command)
        self.assertEqual(proposed["policy"], "ALWAYS_ASK")
        self.policy.create_rule(request, PolicyClass.BLACKLIST)
        with self.assertRaises(TerminalLaunchError):
            self.decide(proposed["proposal_token"], "approve")
        self.assertEqual(self.broker.list_sessions(OWNER), [])

    def test_cancel_and_expiry_prevent_launch(self) -> None:
        clock = [10.0]
        launcher = TerminalLaunchService(self.policy, self.broker, monotonic=lambda: clock[0])
        proposed = launcher.request("/bin/echo cancelled", str(self.root), "HOST_USER", self.authority,
                                    conversation_id="chat-a", turn_id="turn-a")
        self.assertEqual(launcher.decide(proposed["proposal_token"], "cancel", self.authority,
                                         conversation_id="chat-a"), {"cancelled": True})
        with self.assertRaises(TerminalLaunchError):
            launcher.decide(proposed["proposal_token"], "approve", self.authority,
                            conversation_id="chat-a")
        proposed = launcher.request("/bin/echo expired", str(self.root), "HOST_USER", self.authority,
                                    conversation_id="chat-a", turn_id="turn-a")
        clock[0] += 61
        with self.assertRaises(TerminalLaunchError):
            launcher.decide(proposed["proposal_token"], "approve", self.authority,
                            conversation_id="chat-a")
        self.assertEqual(self.broker.list_sessions(OWNER), [])

    def test_conversation_switch_rejects_approval_and_default_only_whitelist(self) -> None:
        proposal = self.request("/bin/echo bind")
        with self.assertRaises(TerminalLaunchError):
            self.launcher.decide(proposal["proposal_token"], "approve", self.authority,
                                 conversation_id="chat-b")
        launched = self.decide(proposal["proposal_token"], "whitelist")
        self.assertTrue(self.broker.owns_session(launched["session_id"], OWNER, "chat-a"))
        self.assertFalse(self.broker.owns_session(launched["session_id"], OWNER, "chat-b"))
        second = self.request("/bin/echo bind")
        self.assertEqual(second["policy"], "WHITELIST")
        self.assertIn("session_id", second)
        high_risk = self.request("sudo /bin/echo high-risk")
        self.assertEqual(high_risk["policy"], "ALWAYS_ASK")
        with self.assertRaises(TerminalLaunchError):
            self.decide(high_risk["proposal_token"], "whitelist")


if __name__ == "__main__":
    unittest.main()
