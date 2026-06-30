from __future__ import annotations

import json
import os
import threading
import unittest
from urllib import error, request
from unittest.mock import patch

from backend.mantlelens.config import MantleLensConfig
from backend.mantlelens.ledger import LEDGER
from backend.mantlelens.live_adapters import LiveWalletAdapter
from backend.mantlelens.onchain import AssessmentRecorderConfig, SignedAssessmentTransactionSender
from backend.mantlelens.server import create_server
from backend.mantlelens.workflows import WalletGuardRunner

from tests.test_p1_live_data_foundation import FakeEtherscan, FakeGoPlus, FakeMoralis, FakeRpc, WALLET


class P2LiveCommitIntegrityTest(unittest.TestCase):
    def setUp(self) -> None:
        LEDGER.records.clear()
        LEDGER.idempotency.clear()

    def test_live_scan_returns_integrity_report_and_evidence_bound_risks(self) -> None:
        response = _live_scan()
        assessment = response["assessment"]
        integrity = response["integrity"]

        self.assertEqual(assessment["dataMode"], "live")
        self.assertFalse(response["coverage"]["missingDataIsSafe"])
        self.assertEqual(integrity["evidenceBinding"]["status"], "pass")
        self.assertEqual(integrity["evidenceBinding"]["orphanClaimCount"], 0)
        self.assertTrue(integrity["topRiskEvidenceBound"])
        self.assertFalse(integrity["sourceIntegrity"]["missingDataIsSafe"])
        self.assertIn(integrity["sourceIntegrity"]["status"], {"pass", "partial"})
        self.assertTrue(integrity["commitEligibility"]["onchainRecordAllowed"])

        evidence_ids = {item["evidenceId"] for item in response["evidenceBundle"]["evidence"]}
        for risk in assessment["topRisks"]:
            self.assertTrue(risk["evidenceIds"])
            self.assertTrue(set(risk["evidenceIds"]).issubset(evidence_ids))

    def test_local_only_commit_does_not_send_onchain_even_when_env_is_configured(self) -> None:
        scan = WalletGuardRunner().scan_wallet(fixture_id="high_risk_wallet", include_explanation=False)
        with patch.dict(os.environ, _onchain_env(), clear=False), patch(
            "backend.mantlelens.onchain.SignedAssessmentTransactionSender.send",
            side_effect=AssertionError("local_only must not sign or send"),
        ):
            commit = _post_commit(
                {
                    "assessment": scan["assessment"],
                    "confirmationReceived": True,
                    "idempotencyKey": "idem_p2_local_only",
                    "recordMode": "local_only",
                }
            )

        record = commit["record"]
        self.assertEqual(record["status"], "recorded_local")
        self.assertEqual(record["commitMode"], "local_only")
        self.assertFalse(record["onchainWriteAttempted"])
        self.assertIsNone(record["assessmentTx"])
        self.assertEqual(record["chainId"], 5000)
        self.assertEqual(record["networkName"], "Mantle Mainnet")

    def test_commit_requires_explicit_confirmation_and_idempotency_key(self) -> None:
        scan = WalletGuardRunner().scan_wallet(fixture_id="high_risk_wallet", include_explanation=False)

        missing_idem = _post_commit_error(
            {
                "assessment": scan["assessment"],
                "confirmationReceived": True,
                "recordMode": "local_only",
            }
        )
        missing_confirmation = _post_commit_error(
            {
                "assessment": scan["assessment"],
                "idempotencyKey": "idem_p2_missing_confirmation",
                "recordMode": "local_only",
            }
        )
        demo_onchain = _post_commit_error(
            {
                "assessment": scan["assessment"],
                "confirmationReceived": True,
                "idempotencyKey": "idem_p2_demo_onchain",
                "recordMode": "onchain",
            }
        )

        self.assertEqual(missing_idem[0], 400)
        self.assertIn("idempotencyKey", missing_idem[1]["message"])
        self.assertEqual(missing_confirmation[0], 400)
        self.assertIn("confirmationReceived", missing_confirmation[1]["message"])
        self.assertEqual(demo_onchain[0], 400)
        self.assertIn("live assessment", demo_onchain[1]["message"])

    def test_onchain_commit_returns_safe_disabled_state_when_recorder_unavailable(self) -> None:
        scan = _live_scan()
        with patch.dict(
            os.environ,
            {
                "MANTLE_CHAIN_ID": "5003",
                "ASSESSMENT_CONTRACT_ADDRESS": "",
                "ASSESSMENT_LOGGER_ADDRESS": "",
                "PRIVATE_KEY": "",
                "WALLET_PRIVATE_KEY": "",
            },
            clear=False,
        ):
            commit = _post_commit(
                {
                    "assessment": scan["assessment"],
                    "confirmationReceived": True,
                    "idempotencyKey": "idem_p2_unavailable_onchain",
                    "recordMode": "onchain",
                }
            )

        record = commit["record"]
        self.assertEqual(record["status"], "pending_unavailable")
        self.assertEqual(record["commitMode"], "onchain_unavailable")
        self.assertFalse(record["onchainRecordAvailable"])
        self.assertFalse(record["onchainWriteAttempted"])
        self.assertIsNone(record["assessmentTx"])
        self.assertEqual(record["chainId"], 5003)
        self.assertEqual(record["networkName"], "Mantle Sepolia")
        self.assertIn("ASSESSMENT_CONTRACT_ADDRESS", record["unavailableReason"])

    def test_explicit_onchain_commit_uses_configured_recorder_for_live_assessment(self) -> None:
        scan = _live_scan()
        with patch.dict(os.environ, _onchain_env(), clear=False), patch(
            "backend.mantlelens.onchain.SignedAssessmentTransactionSender.send",
            return_value="0x" + "f" * 64,
        ) as send:
            commit = _post_commit(
                {
                    "assessment": scan["assessment"],
                    "confirmationReceived": True,
                    "idempotencyKey": "idem_p2_live_onchain",
                    "recordMode": "onchain",
                }
            )

        record = commit["record"]
        self.assertEqual(record["status"], "recorded")
        self.assertEqual(record["commitMode"], "onchain")
        self.assertTrue(record["onchainWriteAttempted"])
        self.assertEqual(record["assessmentTx"], "0x" + "f" * 64)
        self.assertEqual(record["explorerUrl"], "https://sepolia.mantlescan.xyz/tx/" + "0x" + "f" * 64)
        self.assertEqual(record["contractAddress"], "0x" + "a" * 40)
        self.assertEqual(record["chainId"], 5003)
        self.assertEqual(record["networkName"], "Mantle Sepolia")
        self.assertEqual(send.call_count, 1)

    def test_signed_onchain_commit_uses_checksum_contract_address(self) -> None:
        scan = _live_scan()
        signed_tx = type("SignedTx", (), {"raw_transaction": b"\x01\x02"})()
        rpc_results = {
            "eth_getTransactionCount": "0x0",
            "eth_gasPrice": "0x1",
            "eth_estimateGas": "0x5208",
            "eth_sendRawTransaction": "0x" + "9" * 64,
        }
        with patch("backend.mantlelens.onchain.JsonRpcClient.call", side_effect=lambda method, params: rpc_results[method]), patch(
            "eth_account.Account.sign_transaction",
            return_value=signed_tx,
        ) as sign:
            tx_hash = SignedAssessmentTransactionSender(
                AssessmentRecorderConfig(
                    rpc_url="mock://mantle",
                    chain_id=5003,
                    contract_address="0x88507ca2ebcf3c3469fbd6b1085b01b6c147c06c",
                    private_key="1" * 64,
                    explorer_base_url="https://sepolia.mantlescan.xyz",
                )
            ).send(scan["assessment"], assessment_uri="memory://test", trace_id="trace_test")

        tx = sign.call_args.args[0]
        self.assertEqual(tx_hash, "0x" + "9" * 64)
        self.assertEqual(tx["to"], "0x88507CA2EbcF3C3469FbD6b1085B01b6c147C06c")
        self.assertEqual(tx["chainId"], 5003)


def _live_scan() -> dict:
    config = MantleLensConfig(
        mantle_rpc_url="mock://mantle",
        moralis_api_key="mock_moralis",
        moralis_balances_enabled=True,
        moralis_history_enabled=True,
        etherscan_v2_api_key="mock_etherscan",
        goplus_api_key="mock_goplus",
    )
    adapter = LiveWalletAdapter(
        config=config,
        rpc=FakeRpc(),
        goplus=FakeGoPlus(),
        moralis=FakeMoralis(),
        etherscan=FakeEtherscan(),
    )
    return WalletGuardRunner(adapter=adapter).scan_wallet(
        fixture_id="live_wallet",
        wallet_address=WALLET,
        include_explanation=False,
    )


def _post_commit(payload: dict) -> dict:
    status, body = _post_commit_raw(payload)
    if status >= 400:
        raise AssertionError(body)
    return body


def _post_commit_error(payload: dict) -> tuple[int, dict]:
    status, body = _post_commit_raw(payload)
    return status, body


def _post_commit_raw(payload: dict) -> tuple[int, dict]:
    server = create_server("127.0.0.1", 0, quiet=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    opener = request.build_opener(request.ProxyHandler({}))
    try:
        host, port = server.server_address
        req = request.Request(
            f"http://{host}:{port}/api/assessment/commit",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with opener.open(req, timeout=10) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _onchain_env() -> dict[str, str]:
    return {
        "MANTLE_RPC_URL": "mock://mantle",
        "MANTLE_CHAIN_ID": "5003",
        "ASSESSMENT_CONTRACT_ADDRESS": "0x" + "a" * 40,
        "ASSESSMENT_LOGGER_ADDRESS": "0x" + "a" * 40,
        "PRIVATE_KEY": "1" * 64,
        "WALLET_PRIVATE_KEY": "",
        "MANTLE_EXPLORER_BASE_URL": "https://sepolia.mantlescan.xyz",
    }


if __name__ == "__main__":
    unittest.main()
