from __future__ import annotations

import json
import os
import unittest

from backend.injectivelens.adapters import InjectiveAdapterConfig, LiveInjectiveReadOnlyAdapter
from backend.injectivelens.fixtures import DEFAULT_ACCOUNT, build_agent_audit, build_preflight_assessment
from backend.injectivelens.proof import PROOF_STORE, record_assessment_proof, verify_assessment_proof


class Phase0135AcceptanceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.original_tx_hash = os.environ.get("INJECTIVE_PROOF_TX_HASH")
        self.original_block_height = os.environ.get("INJECTIVE_PROOF_BLOCK_HEIGHT")
        PROOF_STORE.records.clear()

    def tearDown(self) -> None:
        self._restore_env("INJECTIVE_PROOF_TX_HASH", self.original_tx_hash)
        self._restore_env("INJECTIVE_PROOF_BLOCK_HEIGHT", self.original_block_height)
        PROOF_STORE.records.clear()

    def test_phase1_live_fallback_is_disclosed_not_pretending_to_be_pure_live(self) -> None:
        assessment = build_preflight_assessment(
            {
                "prompt": "Open a 10x long INJ-PERP using 60% of available margin.",
                "address": DEFAULT_ACCOUNT,
                "network": "injective_testnet",
                "mode": "live_read_only",
            },
            adapter=LiveInjectiveReadOnlyAdapter(config=InjectiveAdapterConfig()),
        )

        serialized = json.dumps(assessment, sort_keys=True)
        self.assertNotIn("demo_fixture:INJ-PERP", serialized)
        self.assertEqual(assessment["marketSnapshot"]["marketId"], "simulated_fixture:INJ-PERP")
        self.assertEqual(assessment["accountState"]["subaccountKind"], "simulation_placeholder")
        self.assertEqual(assessment["sourceCoverage"]["modeSummary"], "Live proof with simulated market/account fixture")
        self.assertIn("unknown", assessment["sourceCoverage"]["explanation"].lower())

    def test_phase2_evidence_has_source_adapter_mode_scope_and_policy_simulation_items(self) -> None:
        assessment = build_preflight_assessment(
            {
                "prompt": "Open a 10x long INJ-PERP using 60% of available margin.",
                "address": DEFAULT_ACCOUNT,
                "network": "injective_testnet",
                "mode": "demo_scenario",
            }
        )

        evidence_by_id = {item["id"]: item for item in assessment["evidence"]}
        self.assertIn("ev_policy_001", evidence_by_id)
        self.assertIn("ev_simulation_001", evidence_by_id)
        for item in assessment["evidence"]:
            self.assertTrue(item.get("adapter"), item)
            self.assertTrue(item.get("sourceKind"), item)
            self.assertTrue(item.get("scope"), item)
            self.assertTrue(item.get("rawRef"), item)
            self.assertIn(item["mode"], {"demo_replay", "live_read_only", "simulated"})

    def test_phase3_agent_audit_trace_covers_decision_loop_and_evidence_refs(self) -> None:
        assessment = build_preflight_assessment(
            {
                "prompt": "Open a 10x long INJ-PERP using 60% of available margin.",
                "address": DEFAULT_ACCOUNT,
                "network": "injective_testnet",
                "mode": "demo_scenario",
            }
        )
        audit = build_agent_audit(assessment)
        tools = [event["tool"] for event in audit["toolTrace"]]

        self.assertGreaterEqual(len(audit["toolTrace"]), 12)
        for expected in [
            "ParseTradeIntent",
            "NormalizeTradeParameters",
            "GetAccountState",
            "GetMarketSnapshot",
            "EvaluateTradeRisk",
            "BindEvidenceBundle",
            "SimulateSaferTrade",
            "DecideExecutionBoundary",
            "GenerateAssessmentHash",
            "RecordAssessment",
            "VerifyAssessment",
        ]:
            self.assertIn(expected, tools)
        self.assertTrue(all("evidenceIds" in event for event in audit["toolTrace"]))
        self.assertIn("Place order", audit["blockedActions"])
        self.assertIn("Verify assessment", audit["allowedActions"])

    def test_phase0_and_phase5_proof_flow_is_preserved_and_scope_is_explicit(self) -> None:
        os.environ["INJECTIVE_PROOF_TX_HASH"] = "0x" + "a" * 64
        os.environ["INJECTIVE_PROOF_BLOCK_HEIGHT"] = "131957156"
        assessment = build_preflight_assessment(
            {
                "prompt": "Open a 10x long INJ-PERP using 60% of available margin.",
                "address": DEFAULT_ACCOUNT,
                "network": "injective_testnet",
                "mode": "demo_scenario",
            }
        )
        self.assertEqual(assessment["proof"]["status"], "ready_to_record")
        self.assertIn("not execution safety, trade outcome, or wallet profitability", assessment["proof"]["message"])

        recorded, status = record_assessment_proof(
            {
                "assessmentId": assessment["assessmentId"],
                "assessmentHash": assessment["assessmentHash"],
                "network": "injective_testnet",
                "confirmation": "user_confirmed_record_assessment",
            },
            assessment,
        )
        self.assertEqual(status, 202)
        self.assertEqual(recorded["status"], "recorded")
        self.assertEqual(recorded["recordedAssessmentHash"], assessment["assessmentHash"])
        self.assertIn("not execution safety, trade outcome, or wallet profitability", recorded["message"])

        verified = verify_assessment_proof(
            {
                "assessmentHash": assessment["assessmentHash"],
                "txHash": recorded["txHash"],
                "network": "injective_testnet",
            },
            {**assessment, "proof": recorded},
        )
        self.assertEqual(verified["status"], "verified_matched")
        self.assertIn("not execution safety, trade outcome, or wallet profitability", verified["message"])

    @staticmethod
    def _restore_env(key: str, value: str | None) -> None:
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
