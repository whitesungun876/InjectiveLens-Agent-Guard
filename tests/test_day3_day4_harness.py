from __future__ import annotations

import copy
import unittest

from backend.mantlelens import (
    EvidenceBindingError,
    FixtureRepository,
    FixtureWalletAdapter,
    evaluate_wallet_risk,
    validate_evidence_binding,
)


class Day3ToolHarnessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = FixtureRepository()
        self.adapter = FixtureWalletAdapter(self.repo)

    def test_all_fixtures_produce_raw_scan_outputs(self) -> None:
        for fixture_id in self.repo.list_fixture_ids():
            with self.subTest(fixture_id=fixture_id):
                raw = self.adapter.scan_raw(fixture_id)
                outputs = raw["toolOutputs"]
                self.assertIn("getKnownTokenBalances", outputs)
                self.assertIn("getTokenApprovals", outputs)
                self.assertIn("getTransferLogs", outputs)
                self.assertIsInstance(outputs["getKnownTokenBalances"]["output"]["balances"], list)
                self.assertIsInstance(outputs["getTokenApprovals"]["output"]["approvals"], list)
                self.assertIsInstance(outputs["getTransferLogs"]["output"]["transfers"], list)

    def test_tc003_indexed_api_unavailable_is_partial_not_safe(self) -> None:
        raw = self.adapter.scan_raw("high_risk_wallet")
        self.assertEqual(raw["sourceAvailability"]["moralis"]["status"], "unavailable")
        self.assertIn(
            raw["toolOutputs"]["getKnownTokenBalances"]["dataCoverage"],
            {"partial", "known-token-only"},
        )
        result = evaluate_wallet_risk(raw)
        self.assertEqual(result["assessment"]["dataStatus"], "PARTIAL_OR_UNKNOWN")
        self.assertNotEqual(result["assessment"]["riskLevel"], "Low")

    def test_tc004_zero_allowance_is_not_active_risk(self) -> None:
        fixture = self.adapter.load_fixture("low_risk_wallet")
        self.assertEqual(self.adapter.active_approvals(fixture), [])
        approval = fixture["approvals"][0]
        confirmation = self.adapter.confirm_active_allowance(
            fixture,
            token_address=approval["tokenAddress"],
            spender=approval["spender"],
        )
        self.assertFalse(confirmation.output["isActive"])
        self.assertEqual(confirmation.output["allowanceRaw"], "0")

    def test_tc005_unlimited_unknown_approval_scores_high(self) -> None:
        raw = self.adapter.scan_raw("high_risk_wallet")
        result = evaluate_wallet_risk(raw)
        assessment = result["assessment"]
        self.assertGreaterEqual(assessment["subScores"]["approvalRisk"], 80)
        approval_risks = [risk for risk in assessment["topRisks"] if risk["type"] == "approval"]
        self.assertTrue(approval_risks)
        evidence_ids = set(approval_risks[0]["evidenceIds"])
        self.assertIn("ev_high_unlimited_approval", evidence_ids)


class Day4RiskEvidenceHarnessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = FixtureWalletAdapter()

    def test_tc006_address_poisoning_candidate_scores_high(self) -> None:
        raw = self.adapter.scan_raw("high_risk_wallet")
        result = evaluate_wallet_risk(raw)
        assessment = result["assessment"]
        self.assertGreaterEqual(assessment["subScores"]["suspiciousTransferRisk"], 75)
        transfer_risks = [risk for risk in assessment["topRisks"] if risk["type"] == "transfer"]
        self.assertTrue(transfer_risks)
        self.assertIn("ev_high_dust_transfer", transfer_risks[0]["evidenceIds"])

    def test_top_risks_and_actions_are_evidence_bound(self) -> None:
        for fixture_id in ["low_risk_wallet", "moderate_partial_wallet", "high_risk_wallet"]:
            with self.subTest(fixture_id=fixture_id):
                result = evaluate_wallet_risk(self.adapter.scan_raw(fixture_id))
                assessment = result["assessment"]
                evidence = result["evidenceBundle"]["evidence"]
                validate_evidence_binding(assessment, evidence)
                for risk in assessment["topRisks"]:
                    self.assertTrue(risk["evidenceIds"])

    def test_tc010_orphan_claim_is_blocked(self) -> None:
        result = evaluate_wallet_risk(self.adapter.scan_raw("high_risk_wallet"))
        assessment = copy.deepcopy(result["assessment"])
        evidence = copy.deepcopy(result["evidenceBundle"]["evidence"])
        assessment["topRisks"][0]["evidenceIds"] = ["ev_missing"]
        with self.assertRaises(EvidenceBindingError):
            validate_evidence_binding(assessment, evidence)

    def test_unknown_circuit_breaker_does_not_mark_safe(self) -> None:
        raw = self.adapter.scan_raw("low_risk_wallet")
        raw["dataCompleteness"]["nativeBalance"] = "unavailable"
        raw["dataCompleteness"]["knownTokenBalances"] = "unavailable"
        raw["dataCompleteness"]["approvalEvents"] = "unavailable"
        raw["dataCompleteness"]["transferLogs"] = "unavailable"
        result = evaluate_wallet_risk(raw)
        assessment = result["assessment"]
        self.assertEqual(assessment["dataStatus"], "PARTIAL_OR_UNKNOWN")
        self.assertNotEqual(assessment["riskLevel"], "Low")
        self.assertEqual(assessment["decisionType"], "SIMULATE_ONLY")

    def test_assessment_hash_is_deterministic_for_same_fixture(self) -> None:
        left = evaluate_wallet_risk(self.adapter.scan_raw("high_risk_wallet"))
        right = evaluate_wallet_risk(self.adapter.scan_raw("high_risk_wallet"))
        self.assertEqual(left["assessment"]["assessmentHash"], right["assessment"]["assessmentHash"])
        self.assertEqual(
            left["evidenceBundle"]["evidenceBundleHash"],
            right["evidenceBundle"]["evidenceBundleHash"],
        )


if __name__ == "__main__":
    unittest.main()
