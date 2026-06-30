from __future__ import annotations

import json
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from backend.injectivelens.fixtures import DEFAULT_ACCOUNT
from backend.injectivelens.protocol import agent_card, agent_registration, call_mcp_tool, mcp_tools
from backend.injectivelens.server import InjectiveLensRequestHandler


ROOT = Path(__file__).resolve().parents[1]


class InjectiveDay9ProtocolTest(unittest.TestCase):
    def test_protocol_static_files_are_valid_injective_json(self) -> None:
        paths = [
            ROOT / "protocol" / "agent-registration.json",
            ROOT / "protocol" / "agent-card.json",
            ROOT / "protocol" / "mcp-tools-list.json",
        ]
        for path in paths:
            with self.subTest(path=path.name):
                data = json.loads(path.read_text())
                rendered = json.dumps(data, sort_keys=True)
                self.assertIsInstance(data, dict)
                self.assertIn("Injective", rendered)
                self.assertNotIn("Mantle", rendered)

    def test_agent_registration_and_card_expose_safety_and_injective_network(self) -> None:
        registration = agent_registration("http://127.0.0.1:8765")
        card = agent_card("http://127.0.0.1:8765")

        self.assertEqual(registration["agentId"], "injectivelens-agent-guard-demo")
        self.assertEqual(registration["chainId"], "injective-888")
        self.assertFalse(registration["safety"]["realExecutionAllowed"])
        self.assertEqual(registration["safety"]["mcpMode"], "read_only_preflight")
        self.assertFalse(card["security"]["realExecutionAllowed"])
        self.assertFalse(card["security"]["privateKeyRequired"])
        self.assertTrue(card["skills"])
        self.assertTrue(any(skill["id"] == "preflight_trade_action" for skill in card["skills"]))

    def test_mcp_tools_are_read_only_and_agent_oriented(self) -> None:
        tools = mcp_tools()
        names = {tool["name"] for tool in tools}

        self.assertIn("preflight_trade_action", names)
        self.assertIn("get_injective_account_state", names)
        self.assertIn("simulate_safer_trade", names)
        self.assertIn("record_assessment_projection", names)
        self.assertTrue(all(tool["annotations"]["readOnlyHint"] for tool in tools))

    def test_mcp_preflight_call_blocks_high_risk_request_without_execution(self) -> None:
        result = call_mcp_tool(
            "preflight_trade_action",
            {
                "prompt": "Open a 10x long INJ-PERP using 60% of available margin.",
                "address": DEFAULT_ACCOUNT,
                "mode": "demo_scenario",
            },
        )

        self.assertEqual(result["assessment"]["decision"], "block")
        self.assertGreaterEqual(result["assessment"]["riskScore"], 80)
        self.assertFalse(result["execution"]["orderPlaced"])
        self.assertFalse(result["execution"]["autoSigningAllowed"])
        self.assertTrue(result["evidence"])
        self.assertEqual(result["audit"]["decision"]["decision"], "block")

    def test_mcp_record_projection_is_read_only(self) -> None:
        result = call_mcp_tool(
            "record_assessment_projection",
            {"assessmentHash": "0xabc", "dryRun": True},
        )

        self.assertEqual(result["status"], "not_mutated")
        self.assertFalse(result["realExecutionAllowed"])
        self.assertEqual(result["requiredConfirmation"], "user_confirmed_record_assessment")

    def test_http_protocol_endpoints_and_mcp_call(self) -> None:
        with _ServerHarness() as harness:
            registration = harness.get("/agent-registration.json")
            card = harness.get("/.well-known/agent-card.json")
            tools = harness.get("/mcp/tools")
            listed = harness.post("/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            scan = harness.post(
                "/mcp",
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "preflight_trade_action",
                        "arguments": {
                            "prompt": "Open a 10x long INJ-PERP using 60% of available margin.",
                            "mode": "demo_scenario",
                        },
                    },
                },
            )
            assessment = harness.post(
                "/api/injective/preflight",
                {
                    "prompt": "Open a 10x long INJ-PERP using 60% of available margin.",
                    "address": DEFAULT_ACCOUNT,
                    "network": "injective_testnet",
                    "mode": "demo_scenario",
                },
            )
            latest = harness.post(
                "/mcp",
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "get_latest_assessment", "arguments": {}},
                },
            )
            health = harness.get("/api/health")

        self.assertEqual(registration["agentId"], "injectivelens-agent-guard-demo")
        self.assertEqual(card["chain"]["chainId"], "injective-888")
        self.assertGreaterEqual(len(tools["tools"]), 7)
        self.assertGreaterEqual(len(listed["result"]["tools"]), 7)
        content = scan["result"]["content"][0]["json"]
        self.assertEqual(content["assessment"]["decision"], "block")
        latest_content = latest["result"]["content"][0]["json"]
        self.assertEqual(latest_content["status"], "available")
        self.assertEqual(latest_content["assessment"]["assessmentId"], assessment["assessmentId"])
        self.assertEqual(health["day"], "9")

    def test_frontend_surfaces_read_only_integration_in_decision_audit(self) -> None:
        app_source = (ROOT / "frontend" / "app" / "src" / "App.tsx").read_text()
        api_source = (ROOT / "frontend" / "app" / "src" / "injectivePreflightApi.ts").read_text()

        self.assertIn("Read-only agent integration surface", app_source)
        self.assertIn("Registry", app_source)
        self.assertIn("Agent card", app_source)
        self.assertIn("MCP tools", app_source)
        self.assertIn("Last checked", app_source)
        self.assertIn("/.well-known/agent-card.json", app_source)
        self.assertIn("/agent-registration.json", app_source)
        self.assertIn("/mcp/tools", app_source)
        self.assertIn("agentIdentity", api_source)

    def test_frontend_decision_audit_prioritizes_boundary_and_collapsed_trace(self) -> None:
        app_source = (ROOT / "frontend" / "app" / "src" / "App.tsx").read_text()

        self.assertIn("This audit view shows why the agent was blocked", app_source)
        self.assertIn("Execution Boundary", app_source)
        self.assertIn("Record assessment hash after explicit confirmation", app_source)
        self.assertIn("View technical trace", app_source)
        self.assertIn("Technical agent trace", app_source)
        self.assertIn("MCP-style read-only agent interface", app_source)
        self.assertIn("This guard never holds private keys, seed phrases, signing rights", app_source)
        self.assertIn("deterministic policy enforces the execution boundary", app_source)
        self.assertNotIn("P0 has no private-key custody", app_source)

    def test_frontend_uses_submission_ready_guard_and_proof_language(self) -> None:
        app_source = (ROOT / "frontend" / "app" / "src" / "App.tsx").read_text()
        api_source = (ROOT / "frontend" / "app" / "src" / "injectivePreflightApi.ts").read_text()

        self.assertIn("A safety and proof layer before AI agents execute trades on Injective.", app_source)
        self.assertIn("InjectiveLens Agent Guard", app_source)
        self.assertIn("Injective Nova build", app_source)
        self.assertNotIn("Pre-execution guard ready", app_source)
        self.assertIn("Run agent guard check", app_source)
        self.assertIn("Assessment hash generated", app_source)
        self.assertIn("Proof recorded on Injective testnet", app_source)
        self.assertIn("Proof verified", app_source)
        self.assertIn("Proof of assessment, not proof of trade execution.", app_source)
        self.assertIn("Agent action template", app_source)
        self.assertIn("Live testnet check", app_source)
        self.assertIn("Live read-only Injective testnet check", app_source)
        self.assertIn("Live source partial · using disclosed simulated fallback", app_source)
        self.assertIn("Demo replay + Injective testnet proof", app_source)
        self.assertIn("Simulation subaccount placeholder", app_source)
        self.assertIn("Data mode", app_source)
        self.assertIn("Source status", app_source)
        self.assertIn("ResultSummaryStrip", app_source)
        self.assertIn("Safer alternative simulated", app_source)
        self.assertIn('id: "E1"', app_source)
        self.assertIn('title: "Account"', app_source)
        self.assertIn('id: "E6"', app_source)
        self.assertIn('title: "Assessment/proof record"', app_source)
        self.assertIn("not trade profitability, execution safety, or wallet outcome", app_source)
        self.assertNotIn("Injective testnet proof ready", app_source)
        self.assertNotIn("demo-inj-perp", app_source)
        self.assertNotIn("Local replay", app_source)
        self.assertNotIn("local_replay", app_source)
        self.assertNotIn("local_replay", api_source)


class _ServerHarness:
    def __enter__(self) -> "_ServerHarness":
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), InjectiveLensRequestHandler)
        self.server.quiet = True  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return self

    def __exit__(self, *_args: object) -> None:
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()

    def get(self, path: str) -> dict[str, object]:
        with self.opener.open(self.base_url + path, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))

    def post(self, path: str, body: dict[str, object]) -> dict[str, object]:
        request = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.opener.open(request, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
