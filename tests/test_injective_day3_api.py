from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from backend.injectivelens.fixtures import DEFAULT_ACCOUNT, build_agent_audit, build_preflight_assessment
from backend.injectivelens.parser import parse_trade_intent
from backend.injectivelens.server import InjectiveLensRequestHandler


class InjectiveDay3ParserTest(unittest.TestCase):
    def test_parses_standard_high_risk_prompt(self) -> None:
        result = parse_trade_intent("Open a 10x long INJ-PERP using 60% of available margin.")
        intent = result["tradeIntent"]
        self.assertEqual(intent["market"], "INJ-PERP")
        self.assertEqual(intent["side"], "long")
        self.assertEqual(intent["orderType"], "market")
        self.assertEqual(intent["leverage"], 10)
        self.assertEqual(intent["marginUsagePct"], 60)
        self.assertGreaterEqual(result["confidence"], 0.9)


class InjectiveDay3AssessmentTest(unittest.TestCase):
    def test_preflight_assessment_matches_day1_contract_shape(self) -> None:
        assessment = build_preflight_assessment(
            {
                "prompt": "Open a 10x long INJ-PERP using 60% of available margin.",
                "address": DEFAULT_ACCOUNT,
                "network": "injective_testnet",
                "mode": "demo_scenario",
            }
        )
        self.assertTrue(assessment["assessmentId"].startswith("preflight_"))
        self.assertTrue(assessment["assessmentHash"].startswith("0x"))
        self.assertEqual(assessment["request"]["mode"], "demo_scenario")
        self.assertEqual(assessment["parseResult"]["tradeIntent"]["market"], "INJ-PERP")
        self.assertEqual(assessment["decision"]["decision"], "block")
        self.assertGreaterEqual(assessment["decision"]["riskScore"], 80)
        self.assertEqual(assessment["proof"]["status"], "ready_to_record")
        self.assertIsNone(assessment["proof"]["recordedAssessmentHash"])
        self.assertTrue(assessment["simulation"]["noBroadcast"])
        self.assertGreaterEqual(len(assessment["evidence"]), 4)

    def test_agent_audit_uses_same_decision_and_blocks_execution(self) -> None:
        assessment = build_preflight_assessment(
            {
                "prompt": "Open a 10x long INJ-PERP using 60% of available margin.",
                "address": DEFAULT_ACCOUNT,
                "network": "injective_testnet",
                "mode": "demo_scenario",
            }
        )
        audit = build_agent_audit(assessment)
        self.assertEqual(audit["assessmentId"], assessment["assessmentId"])
        self.assertEqual(audit["decision"]["decision"], "block")
        self.assertIn("Place order", audit["blockedActions"])
        self.assertTrue(any(event["tool"] == "EvaluateTradeRisk" and event["status"] == "block" for event in audit["toolTrace"]))
        risk_event = next(event for event in audit["toolTrace"] if event["tool"] == "EvaluateTradeRisk")
        self.assertIn(f"{assessment['decision']['riskScore']}/100", risk_event["summary"])


class InjectiveDay3HttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), InjectiveLensRequestHandler)
        cls.server.quiet = True  # type: ignore[attr-defined]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.thread.join(timeout=2)

    def test_http_preflight_history_and_audit(self) -> None:
        assessment = self._post(
            "/api/injective/preflight",
            {
                "prompt": "Open a 10x long INJ-PERP using 60% of available margin.",
                "address": DEFAULT_ACCOUNT,
                "network": "injective_testnet",
                "mode": "demo_scenario",
            },
        )
        self.assertEqual(assessment["decision"]["decision"], "block")
        self.assertEqual(assessment["proof"]["status"], "ready_to_record")

        history = self._get("/api/history/preflight")
        self.assertEqual(history["records"][0]["assessmentId"], assessment["assessmentId"])
        self.assertIn("Assessment hash generated", history["records"][0]["proofStatus"])

        audit = self._get(f"/api/agent/audit?assessmentId={assessment['assessmentId']}")
        self.assertEqual(audit["assessmentId"], assessment["assessmentId"])
        self.assertIn("Auto-sign", audit["blockedActions"])

    def _post(self, path: str, body: dict[str, object]) -> dict[str, object]:
        request = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.opener.open(request, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))

    def _get(self, path: str) -> dict[str, object]:
        with self.opener.open(self.base_url + path, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
