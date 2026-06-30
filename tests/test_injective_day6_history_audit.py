from __future__ import annotations

import json
import os
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from backend.injectivelens.fixtures import DEFAULT_ACCOUNT
from backend.injectivelens.proof import PROOF_STORE
from backend.injectivelens.server import InjectiveLensRequestHandler


class InjectiveDay6HistoryAuditConsistencyTest(unittest.TestCase):
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
        cls.server.server_close()

    def setUp(self) -> None:
        self.original_proof_tx_hash = os.environ.get("INJECTIVE_PROOF_TX_HASH")
        self.original_legacy_proof_tx_hash = os.environ.get("INJECTIVE_TESTNET_PROOF_TX_HASH")
        os.environ.pop("INJECTIVE_PROOF_TX_HASH", None)
        os.environ.pop("INJECTIVE_TESTNET_PROOF_TX_HASH", None)
        PROOF_STORE.records.clear()

    def tearDown(self) -> None:
        self._restore_env("INJECTIVE_PROOF_TX_HASH", self.original_proof_tx_hash)
        self._restore_env("INJECTIVE_TESTNET_PROOF_TX_HASH", self.original_legacy_proof_tx_hash)
        PROOF_STORE.records.clear()

    def test_history_and_audit_follow_record_then_verify_state(self) -> None:
        os.environ["INJECTIVE_PROOF_TX_HASH"] = "B" * 64
        assessment = self._preflight()

        history = self._get("/api/history/preflight")
        self.assertEqual(history["records"][0]["assessmentId"], assessment["assessmentId"])
        self.assertEqual(history["records"][0]["proofStatus"], "Assessment hash generated")

        audit = self._get(f"/api/agent/audit?assessmentId={assessment['assessmentId']}")
        self.assertTrue(any(event["tool"] == "VerifyAssessment" and event["status"] == "skipped" for event in audit["toolTrace"]))

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

        history = self._get("/api/history/preflight")
        self.assertEqual(history["records"][0]["proofStatus"], "Proof recorded on Injective testnet")
        self.assertEqual(history["records"][0]["txHash"], recorded["txHash"])

        audit = self._get(f"/api/agent/audit?assessmentId={assessment['assessmentId']}")
        self.assertTrue(any(event["tool"] == "RecordAssessment" and event["status"] == "completed" for event in audit["toolTrace"]))

        verified = self._post(
            "/api/proof/verify",
            {
                "assessmentHash": assessment["assessmentHash"],
                "txHash": recorded["txHash"],
                "network": "injective_testnet",
            },
        )
        self.assertEqual(verified["status"], "verified_matched")

        history = self._get("/api/history/preflight")
        self.assertEqual(history["records"][0]["proofStatus"], "Proof verified · recorded hash matches")

        audit = self._get(f"/api/agent/audit?assessmentId={assessment['assessmentId']}")
        self.assertTrue(any(event["tool"] == "VerifyAssessment" and event["status"] == "completed" for event in audit["toolTrace"]))

    def test_frontend_consumes_backend_history_and_audit_endpoints(self) -> None:
        app_source = Path("frontend/app/src/App.tsx").read_text()
        api_source = Path("frontend/app/src/injectivePreflightApi.ts").read_text()
        self.assertIn("getPreflightHistory", app_source)
        self.assertIn("getAgentAudit", app_source)
        self.assertIn("/api/history/preflight", api_source)
        self.assertIn("/api/agent/audit", api_source)
        self.assertNotIn("const initialHistory", app_source)

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
