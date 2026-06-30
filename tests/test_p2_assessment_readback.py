from __future__ import annotations

import json
import os
import threading
import unittest
from pathlib import Path
from urllib import request
from unittest.mock import patch

from backend.mantlelens.onchain import (
    ASSESSMENT_ARGUMENT_TYPES,
    ASSESSMENT_EVENT_DATA_TYPES,
    ASSESSMENT_LOGGER_EVENT_SIGNATURE,
    ASSESSMENT_LOGGER_SIGNATURE,
    AssessmentReadbackVerifier,
    AssessmentVerifierConfig,
)
from backend.mantlelens.server import create_server


CONTRACT = "0x" + "a" * 40
SIGNER = "0x" + "b" * 40
TX_HASH = "0x" + "1" * 64
ASSESSMENT_HASH = "0x" + "2" * 64
WALLET_HASH = "0x" + "3" * 64
EVIDENCE_HASH = "0x" + "4" * 64
RECOMMENDATION_HASH = "0x" + "5" * 64
EXPLORER = "https://sepolia.mantlescan.xyz"


class P2AssessmentReadbackTest(unittest.TestCase):
    def test_mock_successful_tx_verification_returns_verified(self) -> None:
        rpc = MockRpc(tx=_assessment_tx(), receipt=_assessment_receipt())
        result = _verifier(rpc).verify_tx(TX_HASH, expected_assessment_hash=ASSESSMENT_HASH)

        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["verificationStatus"], "verified")
        self.assertEqual(result["chainId"], 5003)
        self.assertEqual(result["networkName"], "Mantle Sepolia")
        self.assertEqual(result["contractAddress"], CONTRACT)
        self.assertEqual(result["txHash"], TX_HASH)
        self.assertEqual(result["explorerUrl"], f"{EXPLORER}/tx/{TX_HASH}")
        self.assertEqual(result["blockNumber"], 42)
        self.assertEqual(result["eventName"], "AssessmentRecorded")
        self.assertEqual(result["assessmentHash"], ASSESSMENT_HASH)
        self.assertTrue(result["recordId"])
        self.assertFalse(rpc.sent_transaction)

    def test_mock_failed_tx_returns_failed(self) -> None:
        receipt = _assessment_receipt(status="0x0", logs=[])
        result = _verifier(MockRpc(tx=_assessment_tx(), receipt=receipt)).verify_tx(TX_HASH)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["blockNumber"], 42)

    def test_mock_contract_mismatch_returns_mismatch(self) -> None:
        tx = _assessment_tx()
        tx["to"] = "0x" + "c" * 40

        result = _verifier(MockRpc(tx=tx, receipt=_assessment_receipt())).verify_tx(TX_HASH)

        self.assertEqual(result["status"], "mismatch")
        self.assertIn("target", result["mismatchReason"])

    def test_mock_pending_tx_returns_pending(self) -> None:
        result = _verifier(MockRpc(tx=_assessment_tx(), receipt=None)).verify_tx(TX_HASH)

        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["chainId"], 5003)

    def test_verify_endpoint_does_not_require_private_key_or_leak_secrets(self) -> None:
        rpc = MockRpc(tx=_assessment_tx(), receipt=_assessment_receipt())
        secret = "unit-test-secret-private-key"
        rpc_secret = "sensitive-rpc-key"
        with patch.dict(
            os.environ,
            {
                "MANTLE_RPC_URL": f"https://example.invalid/{rpc_secret}",
                "MANTLE_CHAIN_ID": "5003",
                "ASSESSMENT_CONTRACT_ADDRESS": CONTRACT,
                "ASSESSMENT_LOGGER_ADDRESS": CONTRACT,
                "PRIVATE_KEY": "",
                "WALLET_PRIVATE_KEY": "",
                "SIGNER_PRIVATE_KEY": secret,
                "MANTLE_EXPLORER_BASE_URL": EXPLORER,
            },
            clear=False,
        ), patch("backend.mantlelens.onchain.JsonRpcClient", return_value=rpc):
            payload = _get_json(f"/api/assessment/commit/verify?tx_hash={TX_HASH}&assessment_hash={ASSESSMENT_HASH}")

        rendered = json.dumps(payload, sort_keys=True)
        self.assertEqual(payload["status"], "verified")
        self.assertNotIn(secret, rendered)
        self.assertNotIn(rpc_secret, rendered)
        self.assertFalse(rpc.sent_transaction)

    def test_verify_endpoint_does_not_send_transaction(self) -> None:
        rpc = MockRpc(tx=_assessment_tx(), receipt=_assessment_receipt())
        with patch.dict(
            os.environ,
            {
                "MANTLE_RPC_URL": "mock://mantle-sepolia",
                "MANTLE_CHAIN_ID": "5003",
                "ASSESSMENT_CONTRACT_ADDRESS": CONTRACT,
                "MANTLE_EXPLORER_BASE_URL": EXPLORER,
            },
            clear=False,
        ), patch("backend.mantlelens.onchain.JsonRpcClient", return_value=rpc):
            payload = _get_json(f"/api/assessment/commit/verify?tx_hash={TX_HASH}")

        self.assertEqual(payload["status"], "verified")
        self.assertEqual(rpc.methods, ["eth_chainId", "eth_getTransactionByHash", "eth_getTransactionReceipt"])
        self.assertFalse(rpc.sent_transaction)

    def test_onchain_record_verify_button_does_not_call_commit_handler(self) -> None:
        source = Path("frontend/app/src/App.tsx").read_text(encoding="utf-8")
        self.assertIn("verifyAssessmentCommit", source)
        self.assertIn('data-testid="verify-onchain-record"', source)
        verify_button = source[source.index('data-testid="verify-onchain-record"') : source.index('data-testid="verify-onchain-record"') + 260]
        self.assertIn("onVerifyCommit", verify_button)
        self.assertNotIn("onOnchainCommit", verify_button)
        self.assertNotIn("handleCommit", verify_button)

    def test_qa_scripts_keep_recorder_unavailable_by_default(self) -> None:
        for script in ("scripts/qa_unit.sh", "scripts/qa_integration.sh"):
            text = Path(script).read_text(encoding="utf-8")
            self.assertIn("export PRIVATE_KEY=", text)
            self.assertIn("export WALLET_PRIVATE_KEY=", text)
            self.assertIn("export ASSESSMENT_CONTRACT_ADDRESS=", text)


class MockRpc:
    def __init__(self, *, tx: dict | None, receipt: dict | None, chain_id: str = "0x138b") -> None:
        self.tx = tx
        self.receipt = receipt
        self.chain_id = chain_id
        self.methods: list[str] = []
        self.sent_transaction = False

    def call(self, method: str, params: list) -> object:
        self.methods.append(method)
        if method.startswith("eth_send"):
            self.sent_transaction = True
            raise AssertionError("readback verification must not send transactions")
        if method == "eth_chainId":
            return self.chain_id
        if method == "eth_getTransactionByHash":
            return self.tx
        if method == "eth_getTransactionReceipt":
            return self.receipt
        raise AssertionError(f"unexpected RPC method: {method}")


def _verifier(rpc: MockRpc) -> AssessmentReadbackVerifier:
    return AssessmentReadbackVerifier(
        AssessmentVerifierConfig(
            rpc_url="mock://mantle-sepolia",
            chain_id=5003,
            contract_address=CONTRACT,
            explorer_base_url=EXPLORER,
        ),
        rpc=rpc,
    )


def _assessment_tx() -> dict:
    return {
        "hash": TX_HASH,
        "chainId": "0x138b",
        "to": CONTRACT,
        "input": _assessment_calldata(),
    }


def _assessment_receipt(status: str = "0x1", logs: list[dict] | None = None) -> dict:
    return {
        "transactionHash": TX_HASH,
        "status": status,
        "blockNumber": "0x2a",
        "logs": _assessment_logs() if logs is None else logs,
    }


def _assessment_calldata() -> str:
    from eth_abi import encode
    from eth_utils import keccak

    args = [
        bytes.fromhex(ASSESSMENT_HASH[2:]),
        bytes.fromhex(WALLET_HASH[2:]),
        bytes.fromhex(EVIDENCE_HASH[2:]),
        bytes.fromhex(RECOMMENDATION_HASH[2:]),
        8500,
        "Critical",
        "PAUSE",
        "REVIEW_APPROVAL",
        "memory://test",
    ]
    return "0x" + (keccak(text=ASSESSMENT_LOGGER_SIGNATURE)[:4] + encode(ASSESSMENT_ARGUMENT_TYPES, args)).hex()


def _assessment_logs() -> list[dict]:
    from eth_abi import encode
    from eth_utils import keccak

    data = encode(
        ASSESSMENT_EVENT_DATA_TYPES,
        [
            bytes.fromhex(EVIDENCE_HASH[2:]),
            bytes.fromhex(RECOMMENDATION_HASH[2:]),
            8500,
            "Critical",
            "PAUSE",
            "REVIEW_APPROVAL",
            "memory://test",
        ],
    )
    return [
        {
            "address": CONTRACT,
            "topics": [
                "0x" + keccak(text=ASSESSMENT_LOGGER_EVENT_SIGNATURE).hex(),
                ASSESSMENT_HASH,
                WALLET_HASH,
                "0x" + "0" * 24 + SIGNER[2:],
            ],
            "data": "0x" + data.hex(),
        }
    ]


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


if __name__ == "__main__":
    unittest.main()
