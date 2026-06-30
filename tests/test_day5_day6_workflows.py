from __future__ import annotations

import json
import threading
import unittest
from urllib import request

from backend.mantlelens.policy import PolicyEngine
from backend.mantlelens.server import create_server
from backend.mantlelens.workflows import WalletGuardRunner


class Day5WorkflowTest(unittest.TestCase):
    def test_scan_workflow_returns_assessment_trace_and_coverage(self) -> None:
        runner = WalletGuardRunner()
        response = runner.scan_wallet(fixture_id="high_risk_wallet")

        self.assertIn("assessment", response)
        self.assertIn("trace", response)
        self.assertIn("coverage", response)
        self.assertEqual(response["assessment"]["riskLevel"], "High")
        self.assertEqual(response["assessment"]["dataStatus"], "PARTIAL_OR_UNKNOWN")
        self.assertGreaterEqual(len(response["trace"]["events"]), 8)
        self.assertEqual(response["coverage"]["dataCompleteness"]["fullTokenInventory"], "not_supported_p0")

    def test_rule_fallback_explanation_is_evidence_grounded(self) -> None:
        response = WalletGuardRunner().scan_wallet(fixture_id="high_risk_wallet")
        explanation = response["explanation"]

        self.assertEqual(explanation["mode"], "rule_fallback")
        self.assertTrue(explanation["claimGuardPassed"])
        self.assertTrue(explanation["claims"])
        for claim in explanation["claims"]:
            self.assertTrue(claim["evidenceIds"])

    def test_workflow_state_order_contains_day5_states(self) -> None:
        response = WalletGuardRunner().scan_wallet(fixture_id="moderate_partial_wallet")
        states = [
            event["toState"]
            for event in response["trace"]["events"]
            if event["eventType"] == "agent_state_changed"
        ]
        self.assertEqual(
            states,
            [
                "DATA_GATHERING",
                "PARTIAL_OR_UNKNOWN",
                "RISK_EVALUATING",
                "EVIDENCE_BINDING",
                "EXPLAINING",
                "SIMULATION_READY",
            ],
        )


class Day6PolicyAndApiTest(unittest.TestCase):
    def test_policy_blocks_repeated_tool_call(self) -> None:
        policy = PolicyEngine(max_repeat_calls=2)
        first = policy.allow_tool_call("getNativeBalance", "same_args", current_state="DATA_GATHERING")
        second = policy.allow_tool_call("getNativeBalance", "same_args", current_state="DATA_GATHERING")
        third = policy.allow_tool_call("getNativeBalance", "same_args", current_state="DATA_GATHERING")

        self.assertTrue(first.allowed)
        self.assertTrue(second.allowed)
        self.assertFalse(third.allowed)
        self.assertEqual(third.decision, "block")

    def test_policy_blocks_real_execution_tools(self) -> None:
        policy = PolicyEngine()
        decision = policy.allow_tool_call("revokeApproval", "args", current_state="SIMULATION_READY")
        self.assertFalse(decision.allowed)
        self.assertIn("forbids real", decision.reason)

    def test_commit_guard_requires_confirmation_and_idempotency_key(self) -> None:
        runner = WalletGuardRunner()
        missing_confirmation = runner.simulate_commit_policy_check(
            assessment_hash="0xabc",
            confirmation_received=False,
            idempotency_key="idem_1",
        )
        missing_key = runner.simulate_commit_policy_check(
            assessment_hash="0xabc",
            confirmation_received=True,
            idempotency_key=None,
        )
        allowed = runner.simulate_commit_policy_check(
            assessment_hash="0xabc",
            confirmation_received=True,
            idempotency_key="idem_1",
        )

        self.assertFalse(missing_confirmation["allowed"])
        self.assertFalse(missing_key["allowed"])
        self.assertTrue(allowed["allowed"])

    def test_http_scan_endpoint_returns_real_api_payload(self) -> None:
        server = create_server("127.0.0.1", 0, quiet=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = server.server_address
            payload = json.dumps(
                {
                    "fixtureId": "high_risk_wallet",
                    "includeExplanation": True,
                }
            ).encode("utf-8")
            req = request.Request(
                f"http://{host}:{port}/api/wallet/scan",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            opener = request.build_opener(request.ProxyHandler({}))
            with opener.open(req, timeout=5) as response:
                data = json.loads(response.read().decode("utf-8"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(data["assessment"]["riskLevel"], "High")
        self.assertIn("trace", data)
        self.assertIn("coverage", data)
        self.assertEqual(data["explanation"]["mode"], "rule_fallback")


if __name__ == "__main__":
    unittest.main()
