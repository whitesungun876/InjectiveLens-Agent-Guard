from __future__ import annotations

import json
import threading
import unittest
from urllib import request

from backend.mantlelens.analytics import EVENTS, validate_core_event_traceability
from backend.mantlelens.ledger import LEDGER
from backend.mantlelens.llm_guard import guarded_explanation, validate_llm_claims
from backend.mantlelens.onchain import AssessmentRecorder, AssessmentRecorderConfig
from backend.mantlelens.server import create_server
from backend.mantlelens.simulation import simulate_approval_revoke, simulate_portfolio_adjustment
from backend.mantlelens.workflows import WalletGuardRunner


class Day7LlmAndSimulationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.package = WalletGuardRunner().scan_wallet(fixture_id="high_risk_wallet")
        self.assessment = self.package["assessment"]
        self.evidence = self.package["evidenceBundle"]["evidence"]

    def test_llm_guard_accepts_evidence_grounded_candidate(self) -> None:
        risk = self.assessment["topRisks"][0]
        candidate = {
            "mode": "llm",
            "explanation": risk["claimText"],
            "claims": [
                {
                    "claimText": risk["claimText"],
                    "evidenceIds": risk["evidenceIds"],
                }
            ],
        }
        result = validate_llm_claims(candidate, self.assessment, self.evidence)
        self.assertTrue(result["passed"])
        guarded = guarded_explanation(candidate, self.assessment, self.evidence)
        self.assertEqual(guarded["mode"], "llm")
        self.assertTrue(guarded["claimGuardPassed"])

    def test_llm_guard_rejects_unsupported_claim_and_falls_back(self) -> None:
        candidate = {
            "mode": "llm",
            "explanation": "Your wallet has guaranteed wallet safety.",
            "claims": [
                {
                    "claimText": "Your wallet is guaranteed safe.",
                    "evidenceIds": [],
                }
            ],
        }
        result = validate_llm_claims(candidate, self.assessment, self.evidence)
        self.assertFalse(result["passed"])
        guarded = guarded_explanation(candidate, self.assessment, self.evidence)
        self.assertEqual(guarded["mode"], "rule_fallback")
        self.assertIn("LLM claim guard failed", guarded["fallbackReason"])
        self.assertTrue(guarded["guardFailures"])

    def test_approval_simulation_is_simulation_only(self) -> None:
        simulation = simulate_approval_revoke(self.assessment)
        self.assertEqual(simulation["executionMode"], "simulation_only")
        self.assertFalse(simulation["transactionCreated"])
        self.assertLess(simulation["after"]["walletRiskScore"], simulation["before"]["walletRiskScore"])
        self.assertTrue(simulation["evidenceIds"])

    def test_portfolio_simulation_is_simulation_only(self) -> None:
        simulation = simulate_portfolio_adjustment(self.assessment)
        self.assertEqual(simulation["executionMode"], "simulation_only")
        self.assertFalse(simulation["transactionCreated"])
        self.assertLess(simulation["after"]["walletRiskScore"], simulation["before"]["walletRiskScore"])


class Day8LedgerAndEventsTest(unittest.TestCase):
    def setUp(self) -> None:
        LEDGER.records.clear()
        LEDGER.idempotency.clear()
        LEDGER.recorder = AssessmentRecorder(
            AssessmentRecorderConfig(contract_address=None, private_key=None)
        )
        EVENTS.events.clear()
        self.runner = WalletGuardRunner(ledger=LEDGER)
        self.package = self.runner.scan_wallet(fixture_id="high_risk_wallet")
        self.assessment = self.package["assessment"]

    def test_commit_is_idempotent_and_records_unavailable_onchain_status(self) -> None:
        first = self.runner.commit_assessment(
            self.assessment,
            idempotency_key="idem_test_day8",
            confirmation_received=True,
        )
        second = self.runner.commit_assessment(
            self.assessment,
            idempotency_key="idem_test_day8",
            confirmation_received=True,
        )
        self.assertEqual(first["record"]["assessmentTx"], second["record"]["assessmentTx"])
        self.assertIsNone(first["record"]["assessmentTx"])
        self.assertEqual(first["record"]["status"], "pending_unavailable")
        self.assertEqual(first["record"]["commitMode"], "onchain_unavailable")
        self.assertEqual(first["record"]["assessmentHash"], self.assessment["assessmentHash"])
        self.assertFalse(first["record"]["realExecutionAllowed"])

    def test_benchmark_history_returns_committed_record(self) -> None:
        self.runner.commit_assessment(
            self.assessment,
            idempotency_key="idem_history",
            confirmation_received=True,
        )
        records = LEDGER.history(wallet_hash=self.assessment["wallet"]["walletHash"])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["assessmentId"], self.assessment["assessmentId"])

    def test_core_events_have_run_and_trace_ids(self) -> None:
        simulation = self.runner.simulate(self.assessment, simulation_type="approval_revoke_impact")
        self.runner.commit_assessment(
            self.assessment,
            idempotency_key="idem_events",
            confirmation_received=True,
            simulation=simulation["simulation"],
        )
        self.assertTrue(validate_core_event_traceability(EVENTS.recent()))
        names = {event["eventName"] for event in EVENTS.recent()}
        self.assertIn("simulation_completed", names)
        self.assertIn("assessment_commit_status_changed", names)

    def test_http_simulation_commit_and_benchmark(self) -> None:
        server = create_server("127.0.0.1", 0, quiet=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        opener = request.build_opener(request.ProxyHandler({}))
        try:
            host, port = server.server_address
            scan = self._post_json(
                opener,
                f"http://{host}:{port}/api/wallet/scan",
                {"fixtureId": "high_risk_wallet", "includeExplanation": True},
            )
            simulation = self._post_json(
                opener,
                f"http://{host}:{port}/api/simulation/approval",
                {"assessment": scan["assessment"]},
            )
            commit = self._post_json(
                opener,
                f"http://{host}:{port}/api/assessment/commit",
                {
                    "assessment": scan["assessment"],
                    "simulation": simulation["simulation"],
                    "confirmationReceived": True,
                    "idempotencyKey": "idem_http_day8",
                },
            )
            with opener.open(
                f"http://{host}:{port}/api/benchmark?walletHash={scan['assessment']['wallet']['walletHash']}",
                timeout=5,
            ) as response:
                benchmark = json.loads(response.read().decode("utf-8"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(simulation["simulation"]["executionMode"], "simulation_only")
        self.assertFalse(simulation["simulation"]["transactionCreated"])
        self.assertEqual(commit["record"]["status"], "recorded_local")
        self.assertEqual(commit["record"]["commitMode"], "local_only")
        self.assertIsNone(commit["record"]["assessmentTx"])
        self.assertFalse(commit["record"]["onchainWriteAttempted"])
        self.assertEqual(len(benchmark["records"]), 1)

    def _post_json(self, opener, url: str, payload: dict) -> dict:
        req = request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with opener.open(req, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
