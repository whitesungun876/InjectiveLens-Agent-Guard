from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from backend.mantlelens.ledger import InMemoryLedger
from backend.mantlelens.workflows import WalletGuardRunner


class Phase2ReplayAcceptanceTest(unittest.TestCase):
    def test_prd20_replay_cases_match_expected_decisions_and_actions(self) -> None:
        expected = {
            "stable_wallet": ("Low", "SAFE", "NO_ACTION"),
            "elevated_wallet": ("High", "REVIEW_APPROVAL", "SIMULATE_REVOKE_APPROVAL"),
            "critical_wallet": ("Critical", "PAUSE", "REVIEW_APPROVAL"),
        }
        for fixture_id, expected_tuple in expected.items():
            with self.subTest(fixture_id=fixture_id):
                package = WalletGuardRunner().scan_wallet(fixture_id=fixture_id, include_explanation=False)
                assessment = package["assessment"]
                self.assertEqual(
                    (
                        assessment["riskLevel"],
                        assessment["decisionType"],
                        assessment["actionType"],
                    ),
                    expected_tuple,
                )


class FakeAssessmentRecorder:
    def record_assessment(self, assessment, *, assessment_uri: str, trace_id: str) -> dict:
        return {
            "status": "recorded",
            "commitMode": "onchain",
            "assessmentTx": "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            "explorerUrl": "https://mantlescan.xyz/tx/0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            "onchainRecordAvailable": True,
            "onchainWriteAttempted": True,
            "unavailableReason": None,
            "retryReason": None,
            "contractAddress": "0x1111111111111111111111111111111111111111",
            "signerAddress": "0x2222222222222222222222222222222222222222",
        }


class Phase3OnchainRecordAcceptanceTest(unittest.TestCase):
    def test_missing_onchain_config_returns_pending_unavailable_without_mock_tx(self) -> None:
        env = {
            "ASSESSMENT_CONTRACT_ADDRESS": "",
            "ASSESSMENT_LOGGER_ADDRESS": "",
            "PRIVATE_KEY": "",
            "WALLET_PRIVATE_KEY": "",
        }
        with patch.dict(os.environ, env, clear=False):
            runner = WalletGuardRunner(ledger=InMemoryLedger())
            package = runner.scan_wallet(fixture_id="elevated_wallet", include_explanation=False)
            commit = runner.commit_assessment(
                package["assessment"],
                idempotency_key="idem_phase3_no_key",
                confirmation_received=True,
            )

        record = commit["record"]
        self.assertEqual(record["status"], "pending_unavailable")
        self.assertEqual(record["commitMode"], "onchain_unavailable")
        self.assertIsNone(record["assessmentTx"])
        self.assertIsNone(record["explorerUrl"])
        self.assertFalse(record["onchainRecordAvailable"])
        self.assertFalse(record["onchainWriteAttempted"])
        self.assertNotIn("mock_tx", str(record))
        self.assertIn("ASSESSMENT_CONTRACT_ADDRESS", record["unavailableReason"])

    def test_configured_recorder_persists_real_tx_and_explorer_link(self) -> None:
        ledger = InMemoryLedger(recorder=FakeAssessmentRecorder())
        runner = WalletGuardRunner(ledger=ledger)
        package = runner.scan_wallet(fixture_id="elevated_wallet", include_explanation=False)
        commit = runner.commit_assessment(
            package["assessment"],
            idempotency_key="idem_phase3_recorded",
            confirmation_received=True,
        )

        record = commit["record"]
        self.assertEqual(record["status"], "recorded")
        self.assertEqual(record["commitMode"], "onchain")
        self.assertTrue(record["assessmentTx"].startswith("0x"))
        self.assertIn("/tx/", record["explorerUrl"])
        self.assertTrue(record["onchainRecordAvailable"])
        self.assertTrue(record["onchainWriteAttempted"])


if __name__ == "__main__":
    unittest.main()
