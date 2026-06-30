from __future__ import annotations

import json
import os
import threading
import unittest
from pathlib import Path
from urllib import request
from unittest.mock import patch

from backend.mantlelens.config import MantleLensConfig
from backend.mantlelens.protocol import agent_registration
from backend.mantlelens.server import create_server
from backend.mantlelens.workflows import WalletGuardRunner


class P2PreflightHardeningTest(unittest.TestCase):
    def test_provider_status_uses_configured_chain_and_does_not_leak_secrets(self) -> None:
        secret = "f" * 64
        with patch.dict(
            os.environ,
            {
                "MANTLE_CHAIN_ID": "5003",
                "MANTLE_RPC_URL": "https://example.invalid/sensitive-rpc-key",
                "PRIVATE_KEY": secret,
                "WALLET_PRIVATE_KEY": "",
                "ASSESSMENT_CONTRACT_ADDRESS": "0x" + "a" * 40,
            },
            clear=False,
        ):
            status = MantleLensConfig.from_env().public_provider_status()
            registration = agent_registration("http://127.0.0.1:8765")

        rendered = json.dumps(status, sort_keys=True)
        self.assertEqual(status["chain"]["chainId"], 5003)
        self.assertEqual(status["chain"]["networkName"], "Mantle Sepolia")
        self.assertEqual(registration["chainId"], 5003)
        self.assertEqual(registration["networkName"], "Mantle Sepolia")
        self.assertNotIn(secret, rendered)
        self.assertNotIn("sensitive-rpc-key", rendered)
        self.assertFalse(status["secrets"]["privateKeysExposed"])
        self.assertFalse(status["secrets"]["rawRpcUrlExposed"])

    def test_http_provider_status_is_redacted(self) -> None:
        with patch.dict(
            os.environ,
            {
                "MANTLE_CHAIN_ID": "5003",
                "PRIVATE_KEY": "e" * 64,
                "ASSESSMENT_CONTRACT_ADDRESS": "0x" + "b" * 40,
            },
            clear=False,
        ):
            payload = _get_json("/api/provider/status")

        self.assertEqual(payload["chain"]["displayName"], "Mantle Sepolia · 5003")
        rendered = json.dumps(payload, sort_keys=True)
        self.assertNotIn("e" * 64, rendered)
        self.assertEqual(payload["assessmentLogger"]["status"], "configured")

    def test_demo_high_risk_evidence_resolves_to_detail_panel_data(self) -> None:
        response = WalletGuardRunner().scan_wallet(fixture_id="high_risk_wallet", include_explanation=False)
        integrity = response["integrity"]
        self.assertEqual(integrity["detailResolution"]["status"], "pass")
        self.assertEqual(integrity["detailResolution"]["unresolvedEvidence"], [])

        evidence_by_id = {item["evidenceId"]: item for item in response["evidenceBundle"]["evidence"]}
        approvals = _row_evidence_ids(response["history"]["approvalHistory"]["items"])
        transfers = _row_evidence_ids(response["history"]["transferHistory"]["items"])
        inventory = _row_evidence_ids(response["inventory"]["tokens"])

        for risk in response["assessment"]["topRisks"]:
            self.assertTrue(risk["evidenceIds"])
            for evidence_id in risk["evidenceIds"]:
                evidence_type = evidence_by_id[evidence_id]["type"]
                if evidence_type == "approval":
                    self.assertIn(evidence_id, approvals)
                if evidence_type == "transfer":
                    self.assertIn(evidence_id, transfers)
                if evidence_type == "balance":
                    self.assertIn(evidence_id, inventory)

    def test_scan_does_not_trigger_onchain_commit_automatically(self) -> None:
        with patch(
            "backend.mantlelens.onchain.SignedAssessmentTransactionSender.send",
            side_effect=AssertionError("scan must not commit on-chain"),
        ):
            response = WalletGuardRunner().scan_wallet(fixture_id="high_risk_wallet", include_explanation=False)

        self.assertEqual(response["assessment"]["riskLevel"], "High")
        self.assertTrue(response["assessment"]["topRisks"])

    def test_qa_scripts_clear_onchain_signer_env_for_tests(self) -> None:
        for script in ("scripts/qa_unit.sh", "scripts/qa_integration.sh"):
            text = Path(script).read_text(encoding="utf-8")
            self.assertIn("export PRIVATE_KEY=", text)
            self.assertIn("export WALLET_PRIVATE_KEY=", text)
            self.assertIn("export ASSESSMENT_CONTRACT_ADDRESS=", text)


def _get_json(path: str) -> dict:
    server = create_server("127.0.0.1", 0, quiet=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    opener = request.build_opener(request.ProxyHandler({}))
    try:
        host, port = server.server_address
        with opener.open(f"http://{host}:{port}{path}", timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _row_evidence_ids(rows: list[dict]) -> set[str]:
    ids: set[str] = set()
    for row in rows:
        if row.get("evidenceId"):
            ids.add(row["evidenceId"])
        for evidence_id in row.get("evidenceIds") or []:
            ids.add(evidence_id)
    return ids


if __name__ == "__main__":
    unittest.main()
