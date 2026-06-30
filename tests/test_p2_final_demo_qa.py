from __future__ import annotations

from pathlib import Path
import unittest

from backend.mantlelens.hashutil import stable_hash
from backend.mantlelens.history_store import InMemoryAssessmentHistoryStore


ROOT = Path(__file__).resolve().parents[1]
WALLET = "0x1234567890abcdef1234567890abcdef12345678"
ASSESSMENT_HASH = stable_hash(["p2.5", "assessment"])


class P2FinalDemoQATest(unittest.TestCase):
    def test_commit_and_verify_status_link_to_history_record(self) -> None:
        store = InMemoryAssessmentHistoryStore()
        store.record_scan(**_scan_args())

        commit = {
            "assessmentId": "assessment_p25",
            "assessmentHash": ASSESSMENT_HASH,
            "assessmentTx": "0x" + "1" * 64,
            "explorerUrl": "https://sepolia.mantlescan.xyz/tx/0x" + "1" * 64,
            "status": "recorded",
            "commitMode": "onchain",
            "contractAddress": "0x88507ca2ebcf3c3469fbd6b1085b01b6c147c06c",
        }
        updated = store.attach_commit(commit)

        self.assertIsNotNone(updated)
        latest = store.list_records(address=WALLET, chain_id=5003, mode="live", limit=1)[0]
        self.assertEqual(latest["commitTxHash"], commit["assessmentTx"])
        self.assertEqual(latest["commitStatus"], "recorded")
        self.assertEqual(latest["commitExplorerUrl"], commit["explorerUrl"])

        verification = {
            "txHash": commit["assessmentTx"],
            "verificationStatus": "verified",
            "assessmentHash": ASSESSMENT_HASH,
            "contractAddress": commit["contractAddress"],
            "explorerUrl": commit["explorerUrl"],
        }
        verified = store.attach_commit_verification(verification)

        self.assertIsNotNone(verified)
        latest = store.list_records(address=WALLET, chain_id=5003, mode="live", limit=1)[0]
        self.assertEqual(latest["commitVerificationStatus"], "verified")
        self.assertEqual(latest["assessmentContractAddress"], commit["contractAddress"])

    def test_frontend_manual_revoke_is_review_only(self) -> None:
        source = (ROOT / "frontend/app/src/App.tsx").read_text()
        wallet_revoke_section = source.split("async function handleWalletRevoke", 1)[1].split("return (", 1)[0]
        commit_section = source.split("async function handleCommit", 1)[1].split("async function handleConnectWallet", 1)[0]

        self.assertNotIn("eth_sendTransaction", wallet_revoke_section)
        self.assertNotIn("eth_requestAccounts", wallet_revoke_section)
        self.assertNotIn("wallet_switchEthereumChain", wallet_revoke_section)
        self.assertNotIn("Send to wallet", source)
        self.assertNotIn("Real Manual Revoke", source)
        self.assertIn("prepareAssessmentCommitCalldata", commit_section)
        self.assertIn("eth_sendTransaction", commit_section)
        self.assertIn("Review request", source)
        self.assertIn("wallet execution disabled", source)

    def test_final_demo_smoke_script_covers_p2_5_flow_without_commit(self) -> None:
        script = (ROOT / "scripts/qa_p2_final_demo_smoke.sh").read_text()

        for path in (
            "/api/wallet/scan",
            "/api/wallet/history",
            "/api/wallet/trend",
            "/api/alerts",
            "/api/assessment/commit/verify",
        ):
            self.assertIn(path, script)
        self.assertNotIn('post_json("/api/assessment/commit"', script)
        self.assertIn("assessment_commit_status_changed", script)
        self.assertIn("missingDataIsSafe", script)


def _scan_args() -> dict:
    assessment = {
        "assessmentId": "assessment_p25",
        "timestamp": "2026-06-09T00:00:00+00:00",
        "chainId": 5003,
        "wallet": {"address": WALLET, "walletHash": stable_hash(WALLET.lower())},
        "walletRiskScore": 82,
        "riskLevel": "High",
        "dataConfidence": 0.8,
        "dataStatus": "PARTIAL_OR_UNKNOWN",
        "dataMode": "live",
        "topRisks": [
            {
                "riskId": "risk_p25_approval",
                "type": "approval",
                "category": "approval",
                "title": "Active unlimited approval",
                "severity": "High",
                "scoreImpact": 80,
                "confidence": 0.9,
                "evidenceIds": ["ev_p25_approval"],
            }
        ],
        "suggestedActions": [],
        "assessmentHash": ASSESSMENT_HASH,
        "evidenceBundleHash": stable_hash(["p2.5", "bundle"]),
        "recommendationHash": stable_hash(["p2.5", "recommendation"]),
        "topRisksHash": stable_hash(["p2.5", "risks"]),
    }
    return {
        "assessment": assessment,
        "evidence_bundle": {
            "evidenceBundleHash": assessment["evidenceBundleHash"],
            "evidence": [
                {
                    "evidenceId": "ev_p25_approval",
                    "type": "approval",
                    "source": "unit_fixture",
                    "claimText": "Approval fixture.",
                }
            ],
        },
        "coverage": {
            "dataStatus": "PARTIAL_OR_UNKNOWN",
            "dataCompleteness": {"approvalHistory": "available"},
            "sourceAvailability": {"etherscanV2": {"status": "available"}},
            "missingDataIsSafe": False,
        },
        "inventory": None,
        "history": None,
    }


if __name__ == "__main__":
    unittest.main()
