from __future__ import annotations

import unittest

from backend.mantlelens.workflows import WalletGuardRunner


class P26BenchmarkCasesTest(unittest.TestCase):
    def scan(self, fixture_id: str) -> dict:
        return WalletGuardRunner().scan_wallet(fixture_id=fixture_id, include_explanation=False)

    def risk_ids(self, result: dict) -> set[str]:
        return {risk.get("riskId") or risk.get("risk_id") for risk in result["assessment"]["topRisks"]}

    def test_benchmark_cases_have_distinct_signal_behaviors(self) -> None:
        cases = {
            "multi_signal": "high_risk_wallet",
            "approval_anomaly": "elevated_wallet",
            "address_poisoning": "address_poisoning_wallet",
            "yield_concentration": "yield_concentration_wallet",
            "partial_coverage": "moderate_partial_wallet",
            "quiet_wallet": "quiet_wallet",
            "critical_risk": "critical_wallet",
        }
        results = {case: self.scan(fixture) for case, fixture in cases.items()}

        self.assertIn("risk_approval_unknown_unlimited", self.risk_ids(results["multi_signal"]))
        self.assertIn("risk_transfer_address_poisoning", self.risk_ids(results["multi_signal"]))
        self.assertIn("risk_rwa_yield_exposure", self.risk_ids(results["multi_signal"]))

        self.assertIn("risk_approval_unknown_unlimited", self.risk_ids(results["approval_anomaly"]))
        self.assertIn("risk_transfer_address_poisoning", self.risk_ids(results["address_poisoning"]))
        self.assertIn("risk_rwa_yield_exposure", self.risk_ids(results["yield_concentration"]))
        self.assertIn("risk_source_coverage_partial", self.risk_ids(results["partial_coverage"]))
        self.assertIn("risk_wallet_activity_unknown", self.risk_ids(results["quiet_wallet"]))

    def test_quiet_wallet_is_unknown_coverage_not_safe(self) -> None:
        result = self.scan("quiet_wallet")
        assessment = result["assessment"]

        self.assertEqual(assessment["dataStatus"], "PARTIAL_OR_UNKNOWN")
        self.assertEqual(assessment["riskLevel"], "Moderate")
        self.assertNotEqual(assessment["decisionType"], "SAFE")
        self.assertTrue(assessment["topRisks"])
        self.assertTrue(all(risk["evidenceIds"] for risk in assessment["topRisks"]))

    def test_critical_case_uses_blocking_pause_decision(self) -> None:
        result = self.scan("critical_wallet")
        assessment = result["assessment"]

        self.assertEqual(assessment["riskLevel"], "Critical")
        self.assertEqual(assessment["decisionType"], "PAUSE")
        self.assertEqual(assessment["actionType"], "REVIEW_APPROVAL")
        self.assertTrue(any(risk.get("isBlocking") for risk in assessment["topRisks"]))

    def test_history_record_preserves_benchmark_case_metadata(self) -> None:
        result = WalletGuardRunner().scan_wallet(
            fixture_id="high_risk_wallet",
            include_explanation=False,
            benchmark_case={"id": "multi_signal", "label": "Multi-signal wallet"},
        )
        assessment = result["assessment"]
        record = result["assessmentHistoryRecord"]

        self.assertEqual(assessment["fixtureId"], "high_risk_wallet")
        self.assertEqual(assessment["benchmarkCase"]["id"], "multi_signal")
        self.assertEqual(record["fixtureId"], "high_risk_wallet")
        self.assertEqual(record["benchmarkCaseId"], "multi_signal")
        self.assertEqual(record["benchmarkCaseLabel"], "Multi-signal wallet")


if __name__ == "__main__":
    unittest.main()
