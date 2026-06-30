from __future__ import annotations

import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from backend.injectivelens.fixtures import DEFAULT_ACCOUNT
from backend.injectivelens.proof import PROOF_STORE
from backend.injectivelens.server import InjectiveLensRequestHandler


class InjectiveDay5ProofBoundaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), InjectiveLensRequestHandler)
        cls.server.quiet = True  # type: ignore[attr-defined]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.thread.join(timeout=2)

    def setUp(self) -> None:
        self.original_proof_tx_hash = os.environ.get("INJECTIVE_PROOF_TX_HASH")
        self.original_legacy_proof_tx_hash = os.environ.get("INJECTIVE_TESTNET_PROOF_TX_HASH")
        self.original_proof_block_height = os.environ.get("INJECTIVE_PROOF_BLOCK_HEIGHT")
        os.environ.pop("INJECTIVE_PROOF_TX_HASH", None)
        os.environ.pop("INJECTIVE_TESTNET_PROOF_TX_HASH", None)
        os.environ.pop("INJECTIVE_PROOF_BLOCK_HEIGHT", None)
        PROOF_STORE.records.clear()

    def tearDown(self) -> None:
        self._restore_env("INJECTIVE_PROOF_TX_HASH", self.original_proof_tx_hash)
        self._restore_env("INJECTIVE_TESTNET_PROOF_TX_HASH", self.original_legacy_proof_tx_hash)
        self._restore_env("INJECTIVE_PROOF_BLOCK_HEIGHT", self.original_proof_block_height)
        PROOF_STORE.records.clear()

    def test_preflight_does_not_auto_record_or_auto_verify(self) -> None:
        assessment = self._preflight()
        self.assertEqual(assessment["proof"]["status"], "ready_to_record")
        self.assertEqual(assessment["proof"]["proofMethod"], "tx_memo")
        self.assertIsNone(assessment["proof"]["txHash"])

    def test_record_requires_explicit_confirmation(self) -> None:
        assessment = self._preflight()
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self._post(
                "/api/proof/record",
                {
                    "assessmentId": assessment["assessmentId"],
                    "assessmentHash": assessment["assessmentHash"],
                    "network": "injective_testnet",
                },
            )
        raised.exception.close()
        self.assertEqual(raised.exception.code, 400)

    def test_record_without_configured_tx_is_pending(self) -> None:
        assessment = self._preflight()
        recorded = self._post(
            "/api/proof/record",
            {
                "assessmentId": assessment["assessmentId"],
                "assessmentHash": assessment["assessmentHash"],
                "network": "injective_testnet",
                "confirmation": "user_confirmed_record_assessment",
            },
        )
        self.assertEqual(recorded["status"], "pending")
        self.assertEqual(recorded["recordedAssessmentHash"], assessment["assessmentHash"])
        self.assertIsNone(recorded["txHash"])
        self.assertIn("INJECTIVE_PROOF_TX_HASH", recorded["message"])

        verified = self._post(
            "/api/proof/verify",
            {
                "assessmentHash": assessment["assessmentHash"],
                "network": "injective_testnet",
            },
        )
        self.assertEqual(verified["status"], "not_found")

    def test_record_then_verify_updates_history_with_configured_testnet_tx(self) -> None:
        os.environ["INJECTIVE_PROOF_TX_HASH"] = "A" * 64
        os.environ["INJECTIVE_PROOF_BLOCK_HEIGHT"] = "61234567"
        assessment = self._preflight()
        recorded = self._post(
            "/api/proof/record",
            {
                "assessmentId": assessment["assessmentId"],
                "assessmentHash": assessment["assessmentHash"],
                "network": "injective_testnet",
                "confirmation": "user_confirmed_record_assessment",
            },
        )
        self.assertEqual(recorded["status"], "recorded")
        self.assertEqual(recorded["recordedAssessmentHash"], assessment["assessmentHash"])
        self.assertTrue(recorded["txHash"])
        self.assertEqual(recorded["blockHeight"], 61234567)

        verified = self._post(
            "/api/proof/verify",
            {
                "assessmentHash": assessment["assessmentHash"],
                "txHash": recorded["txHash"],
                "network": "injective_testnet",
            },
        )
        self.assertEqual(verified["status"], "verified_matched")
        self.assertEqual(verified["onchainAssessmentHash"], assessment["assessmentHash"])

        history = self._get("/api/history/preflight")
        self.assertIn("Proof verified", history["records"][0]["proofStatus"])

    def test_verify_before_record_returns_not_found(self) -> None:
        assessment = self._preflight()
        verified = self._post(
            "/api/proof/verify",
            {
                "assessmentHash": assessment["assessmentHash"],
                "network": "injective_testnet",
            },
        )
        self.assertEqual(verified["status"], "not_found")

    def _preflight(self) -> dict[str, object]:
        return self._post(
            "/api/injective/preflight",
            {
                "prompt": "Open a 10x long INJ-PERP using 60% of available margin.",
                "address": DEFAULT_ACCOUNT,
                "network": "injective_testnet",
                "mode": "demo_scenario",
            },
        )

    def _post(self, path: str, body: dict[str, object]) -> dict[str, object]:
        request = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.opener.open(request, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))

    def _get(self, path: str) -> dict[str, object]:
        with self.opener.open(self.base_url + path, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _restore_env(key: str, value: str | None) -> None:
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
