from __future__ import annotations

import copy
import unittest

from backend.mantlelens import FixtureWalletAdapter, validate_evidence_binding
from backend.mantlelens.config import KnownToken, MantleLensConfig
from backend.mantlelens.live_adapters import LiveWalletAdapter
from backend.mantlelens.workflows import WalletGuardRunner

from tests.test_p1_live_data_foundation import FakeRpc, TOKEN, WALLET


class P2RiskEngineHardeningTest(unittest.TestCase):
    def test_risk_output_contract_and_evidence_resolution(self) -> None:
        response = WalletGuardRunner().scan_wallet(fixture_id="high_risk_wallet", include_explanation=False)
        assessment = response["assessment"]
        evidence_ids = {item["evidenceId"] for item in response["evidenceBundle"]["evidence"]}

        self.assertIn("riskEngine", assessment)
        self.assertIn("scoreBreakdown", assessment)
        for risk in assessment["topRisks"] + assessment["riskEngine"]["allRisks"]:
            for key in (
                "risk_id",
                "title",
                "severity",
                "category",
                "score_impact",
                "confidence",
                "evidence_ids",
                "source_status",
                "explanation",
                "recommended_safe_actions",
                "is_blocking",
                "unknowns",
            ):
                self.assertIn(key, risk)
            self.assertTrue(risk["evidenceIds"])
            self.assertTrue(set(risk["evidenceIds"]).issubset(evidence_ids))

    def test_risk_engine_rejects_top_risks_without_evidence_ids(self) -> None:
        response = WalletGuardRunner().scan_wallet(fixture_id="high_risk_wallet", include_explanation=False)
        assessment = copy.deepcopy(response["assessment"])
        assessment["topRisks"][0]["evidenceIds"] = []

        with self.assertRaises(Exception):
            validate_evidence_binding(assessment, response["evidenceBundle"]["evidence"])

    def test_missing_approval_and_transfer_sources_are_unknown_not_safe(self) -> None:
        response = _live_partial_scan()
        assessment = response["assessment"]
        claims = " ".join(risk["explanation"].lower() for risk in assessment["riskEngine"]["allRisks"])

        self.assertEqual(assessment["dataStatus"], "PARTIAL_OR_UNKNOWN")
        self.assertFalse(response["coverage"]["missingDataIsSafe"])
        self.assertNotIn("safe approval", claims)
        self.assertNotIn("safe transfer", claims)
        self.assertTrue(any(risk["category"] in {"source_coverage", "wallet_activity"} for risk in assessment["riskEngine"]["allRisks"]))

    def test_partial_provider_data_lowers_confidence_without_fake_safety(self) -> None:
        stable = WalletGuardRunner().scan_wallet(fixture_id="stable_wallet", include_explanation=False)["assessment"]
        partial = _live_partial_scan()["assessment"]

        self.assertEqual(stable["dataConfidence"], 1.0)
        self.assertLess(partial["dataConfidence"], stable["dataConfidence"])
        self.assertEqual(partial["dataStatus"], "PARTIAL_OR_UNKNOWN")

    def test_unlimited_approval_with_evidence_produces_high_severity(self) -> None:
        assessment = WalletGuardRunner().scan_wallet(fixture_id="high_risk_wallet", include_explanation=False)["assessment"]
        approval = next(risk for risk in assessment["riskEngine"]["allRisks"] if risk["category"] == "approval")

        self.assertGreaterEqual(approval["scoreImpact"], 80)
        self.assertEqual(approval["severity"], "High")
        self.assertIn("ev_high_unlimited_approval", approval["evidenceIds"])

    def test_dust_transfer_with_evidence_produces_poisoning_warning(self) -> None:
        assessment = WalletGuardRunner().scan_wallet(fixture_id="high_risk_wallet", include_explanation=False)["assessment"]
        transfer = next(risk for risk in assessment["riskEngine"]["allRisks"] if risk["category"] == "transfer")

        self.assertGreaterEqual(transfer["scoreImpact"], 75)
        self.assertIn("address poisoning", transfer["explanation"].lower())
        self.assertIn("ev_high_dust_transfer", transfer["evidenceIds"])

    def test_token_concentration_uses_inventory_evidence(self) -> None:
        response = WalletGuardRunner().scan_wallet(fixture_id="critical_wallet", include_explanation=False)
        evidence_by_id = {item["evidenceId"]: item for item in response["evidenceBundle"]["evidence"]}
        concentration = next(risk for risk in response["assessment"]["riskEngine"]["allRisks"] if risk["category"] == "concentration")

        self.assertTrue(concentration["evidenceIds"])
        self.assertTrue(all(evidence_by_id[evidence_id]["type"] == "balance" for evidence_id in concentration["evidenceIds"]))

    def test_demo_high_risk_wallet_produces_stable_expected_risks(self) -> None:
        assessment = WalletGuardRunner().scan_wallet(fixture_id="high_risk_wallet", include_explanation=False)["assessment"]

        self.assertEqual(assessment["riskLevel"], "High")
        self.assertEqual(
            [risk["category"] for risk in assessment["topRisks"]],
            ["approval", "transfer", "rwa_yield"],
        )

    def test_live_partial_data_is_not_safe(self) -> None:
        response = _live_partial_scan()
        assessment = response["assessment"]

        self.assertEqual(assessment["dataMode"], "live")
        self.assertEqual(assessment["dataStatus"], "PARTIAL_OR_UNKNOWN")
        self.assertNotEqual(assessment["decisionType"], "SAFE")
        self.assertFalse(response["coverage"]["missingDataIsSafe"])

    def test_suggested_actions_are_non_executing(self) -> None:
        assessment = WalletGuardRunner().scan_wallet(fixture_id="high_risk_wallet", include_explanation=False)["assessment"]
        allowed_modes = {"simulation_only", "view_only"}
        forbidden = {"execute", "server_signed", "broadcast", "swap", "trade"}

        for action in assessment["suggestedActions"]:
            self.assertIn(action["executionMode"], allowed_modes)
            rendered = " ".join(str(value).lower() for value in action.values())
            self.assertFalse(any(term in rendered for term in forbidden))

    def test_score_explanation_maps_to_final_score(self) -> None:
        assessment = WalletGuardRunner().scan_wallet(fixture_id="high_risk_wallet", include_explanation=False)["assessment"]
        breakdown = assessment["scoreBreakdown"]

        self.assertEqual(
            round(sum(metric["weightedContribution"] for metric in assessment["metricResults"]), 2),
            assessment["walletRiskScore"],
        )
        self.assertEqual(breakdown["weightedMetricSum"], assessment["walletRiskScore"])
        self.assertEqual(breakdown["totalScore"], assessment["walletRiskScore"])
        self.assertTrue(breakdown["riskContributions"])


def _live_partial_scan() -> dict:
    config = MantleLensConfig(
        mantle_rpc_url="mock://mantle",
        known_tokens=(KnownToken("USDT", TOKEN, 6, 1.0),),
    )
    adapter = LiveWalletAdapter(config=config, rpc=FakeRpc())
    return WalletGuardRunner(adapter=adapter).scan_wallet(
        fixture_id="live_wallet",
        wallet_address=WALLET,
        include_explanation=False,
    )


if __name__ == "__main__":
    unittest.main()
