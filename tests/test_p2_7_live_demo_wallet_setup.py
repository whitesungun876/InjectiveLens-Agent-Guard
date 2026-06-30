from __future__ import annotations

import json
import os
import threading
import unittest
from pathlib import Path
from urllib import error, request
from unittest.mock import patch

from backend.mantlelens.onchain import build_assessment_commit_calldata
from backend.mantlelens.server import create_server


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = "0x" + "a" * 40


class P27LiveDemoWalletSetupTest(unittest.TestCase):
    def test_demo_contract_and_setup_helper_exist(self) -> None:
        self.assertTrue((ROOT / "contracts" / "MantleLensDemoToken.sol").exists())
        self.assertTrue((ROOT / "scripts" / "build_p2_7_demo_contracts.py").exists())
        self.assertTrue((ROOT / "frontend" / "app" / "public" / "p2_7_live_wallet_setup.html").exists())
        self.assertTrue((ROOT / "docs" / "P2_7_LIVE_DEMO_WALLET.md").exists())

    def test_setup_helper_uses_wallet_popups_without_auto_connect_or_private_key_input(self) -> None:
        html = (ROOT / "frontend" / "app" / "public" / "p2_7_live_wallet_setup.html").read_text(encoding="utf-8")
        self.assertIn("eth_sendTransaction", html)
        self.assertIn("eth_requestAccounts", html)
        self.assertIn("wallet_switchEthereumChain", html)
        self.assertNotIn("eth_sendRawTransaction", html)
        self.assertNotIn("localStorage", html)
        self.assertNotIn("seed phrase", html.lower())
        self.assertNotIn("private key input", html.lower())
        connect_call = "connectWallet();"
        self.assertNotIn(connect_call, html)

    def test_build_script_does_not_read_or_print_signer_secrets(self) -> None:
        script = (ROOT / "scripts" / "build_p2_7_demo_contracts.py").read_text(encoding="utf-8")
        self.assertNotIn("PRIVATE_KEY", script)
        self.assertNotIn("WALLET_PRIVATE_KEY", script)
        self.assertNotIn("SIGNER_PRIVATE_KEY", script)
        self.assertNotIn(".env", script)

    def test_calldata_builder_requires_no_private_key_and_does_not_attempt_write(self) -> None:
        secret = "unit-test-wallet-secret"
        with patch.dict(
            os.environ,
            {
                "MANTLE_CHAIN_ID": "5003",
                "ASSESSMENT_CONTRACT_ADDRESS": CONTRACT,
                "PRIVATE_KEY": secret,
                "WALLET_PRIVATE_KEY": secret,
                "SIGNER_PRIVATE_KEY": secret,
            },
            clear=False,
        ):
            payload = build_assessment_commit_calldata(_live_assessment())

        rendered = json.dumps(payload, sort_keys=True)
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["chainId"], 5003)
        self.assertEqual(payload["to"], CONTRACT)
        self.assertTrue(payload["data"].startswith("0x"))
        self.assertFalse(payload["privateKeyRequired"])
        self.assertTrue(payload["walletConfirmationRequired"])
        self.assertFalse(payload["onchainWriteAttempted"])
        self.assertNotIn(secret, rendered)

    def test_commit_calldata_endpoint_rejects_replay_and_returns_safe_live_payload(self) -> None:
        with patch.dict(
            os.environ,
            {
                "MANTLE_CHAIN_ID": "5003",
                "ASSESSMENT_CONTRACT_ADDRESS": CONTRACT,
                "PRIVATE_KEY": "",
                "WALLET_PRIVATE_KEY": "",
            },
            clear=False,
        ):
            live = _post_json("/api/assessment/commit/calldata", {"assessment": _live_assessment()})
            replay_status, replay = _post_json_raw(
                "/api/assessment/commit/calldata",
                {"assessment": {**_live_assessment(), "dataMode": "demo"}},
            )

        self.assertEqual(live["status"], "ready")
        self.assertEqual(live["networkName"], "Mantle Sepolia")
        self.assertFalse(live["privateKeyRequired"])
        self.assertFalse(live["onchainWriteAttempted"])
        self.assertEqual(replay_status, 400)
        self.assertIn("live assessment", replay["message"])

    def test_env_example_documents_public_allowlist_only(self) -> None:
        example = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn("MANTLE_KNOWN_TOKENS_JSON", example)
        self.assertIn("MLDT", example)
        self.assertIn("https://rpc.sepolia.mantle.xyz", example)


def _live_assessment() -> dict:
    return {
        "assessmentId": "assessment_p2_7_live",
        "dataMode": "live",
        "chainId": 5003,
        "assessmentHash": "0x" + "1" * 64,
        "wallet": {
            "address": "0x" + "2" * 40,
            "walletHash": "0x" + "3" * 64,
        },
        "evidenceBundleHash": "0x" + "4" * 64,
        "recommendationHash": "0x" + "5" * 64,
        "walletRiskScore": 60,
        "riskLevel": "High",
        "decisionType": "REVIEW_APPROVAL",
        "actionType": "SIMULATE_REVOKE_APPROVAL",
    }


def _post_json(path: str, payload: dict) -> dict:
    status, body = _post_json_raw(path, payload)
    if status >= 400:
        raise AssertionError(body)
    return body


def _post_json_raw(path: str, payload: dict) -> tuple[int, dict]:
    server = create_server("127.0.0.1", 0, quiet=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    req = request.Request(
        f"http://{host}:{port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    opener = request.build_opener(request.ProxyHandler({}))
    try:
        try:
            with opener.open(req, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    unittest.main()
