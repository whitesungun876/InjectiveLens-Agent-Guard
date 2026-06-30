from __future__ import annotations

import json
import threading
import time
import unittest
from pathlib import Path
from urllib import request

from backend.mantlelens.ledger import LEDGER
from backend.mantlelens.onchain import AssessmentRecorder, AssessmentRecorderConfig
from backend.mantlelens.protocol import agent_card, agent_registration, call_mcp_tool, mcp_tools
from backend.mantlelens.server import create_server
from backend.mantlelens.workflows import WalletGuardRunner


ROOT = Path(__file__).resolve().parents[1]


class Day9ProtocolHarnessTest(unittest.TestCase):
    def setUp(self) -> None:
        LEDGER.records.clear()
        LEDGER.idempotency.clear()
        LEDGER.recorder = AssessmentRecorder(
            AssessmentRecorderConfig(contract_address=None, private_key=None)
        )

    def test_protocol_static_files_are_valid_json(self) -> None:
        paths = [
            ROOT / "protocol" / "agent-registration.json",
            ROOT / "protocol" / "agent-card.json",
            ROOT / "protocol" / "mcp-tools-list.json",
        ]
        for path in paths:
            with self.subTest(path=path.name):
                data = json.loads(path.read_text())
                self.assertIsInstance(data, dict)

    def test_agent_registration_and_card_have_safety_flags(self) -> None:
        registration = agent_registration("http://127.0.0.1:8765")
        card = agent_card("http://127.0.0.1:8765")

        self.assertEqual(registration["chainId"], 5000)
        self.assertFalse(registration["safety"]["realExecutionAllowed"])
        self.assertEqual(registration["safety"]["mcpMode"], "read_only")
        self.assertFalse(card["security"]["realExecutionAllowed"])
        self.assertTrue(card["skills"])

    def test_mcp_tools_are_read_only(self) -> None:
        tools = mcp_tools()
        names = {tool["name"] for tool in tools}
        self.assertIn("scan_wallet_risk", names)
        self.assertIn("get_evidence_bundle", names)
        self.assertIn("record_wallet_assessment", names)
        self.assertTrue(all(tool["annotations"]["readOnlyHint"] for tool in tools))

    def test_mcp_read_only_record_projection_does_not_mutate_ledger(self) -> None:
        response = call_mcp_tool(
            "record_wallet_assessment",
            {"assessmentHash": "0xabc", "dryRun": True},
        )
        self.assertEqual(response["status"], "not_mutated")
        self.assertFalse(response["realExecutionAllowed"])
        self.assertEqual(LEDGER.history(), [])

    def test_http_protocol_endpoints_and_mcp_call(self) -> None:
        server = create_server("127.0.0.1", 0, quiet=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        opener = request.build_opener(request.ProxyHandler({}))
        try:
            host, port = server.server_address
            base = f"http://{host}:{port}"
            registration = self._get_json(opener, f"{base}/agent-registration.json")
            card = self._get_json(opener, f"{base}/.well-known/agent-card.json")
            tools = self._post_json(opener, f"{base}/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            scan = self._post_json(
                opener,
                f"{base}/mcp",
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "scan_wallet_risk",
                        "arguments": {"fixtureId": "high_risk_wallet"},
                    },
                },
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(registration["agentId"], "mantlelens-wallet-guard-demo")
        self.assertTrue(card["skills"])
        self.assertGreaterEqual(len(tools["result"]["tools"]), 7)
        content = scan["result"]["content"][0]["json"]
        self.assertEqual(content["assessment"]["riskLevel"], "High")

    def _get_json(self, opener, url: str) -> dict:
        with opener.open(url, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def _post_json(self, opener, url: str, payload: dict) -> dict:
        req = request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with opener.open(req, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))


class Day10DemoFreezeHarnessTest(unittest.TestCase):
    def setUp(self) -> None:
        LEDGER.records.clear()
        LEDGER.idempotency.clear()
        LEDGER.recorder = AssessmentRecorder(
            AssessmentRecorderConfig(contract_address=None, private_key=None)
        )

    def test_standard_demo_runs_three_times(self) -> None:
        durations = []
        for index in range(3):
            started = time.perf_counter()
            runner = WalletGuardRunner(ledger=LEDGER)
            package = runner.scan_wallet(fixture_id="high_risk_wallet")
            simulation = runner.simulate(package["assessment"], simulation_type="approval_revoke_impact")
            commit = runner.commit_assessment(
                package["assessment"],
                idempotency_key=f"idem_demo_freeze_{index}",
                confirmation_received=True,
                simulation=simulation["simulation"],
            )
            durations.append(time.perf_counter() - started)

            self.assertEqual(package["assessment"]["riskLevel"], "High")
            self.assertEqual(package["assessment"]["dataStatus"], "PARTIAL_OR_UNKNOWN")
            self.assertEqual(simulation["simulation"]["executionMode"], "simulation_only")
            self.assertFalse(simulation["simulation"]["transactionCreated"])
            self.assertEqual(commit["record"]["status"], "pending_unavailable")
            self.assertIsNone(commit["record"]["assessmentTx"])
            self.assertFalse(commit["record"]["realExecutionAllowed"])

        self.assertEqual(len(LEDGER.history()), 3)
        self.assertTrue(all(duration < 5 for duration in durations))

    def test_fallback_demo_can_run_without_http_server(self) -> None:
        package = WalletGuardRunner().scan_wallet(fixture_id="high_risk_wallet")
        self.assertEqual(package["assessment"]["riskLevel"], "High")
        self.assertEqual(package["explanation"]["mode"], "rule_fallback")
        self.assertTrue(package["evidenceBundle"]["evidence"])


if __name__ == "__main__":
    unittest.main()
