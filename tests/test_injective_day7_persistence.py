from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from backend.injectivelens.fixtures import DEFAULT_ACCOUNT
from backend.injectivelens.persistence import JsonStateStore
from backend.injectivelens.proof import PROOF_STORE
from backend.injectivelens.server import InjectiveLensRequestHandler
import backend.injectivelens.server as server_module


class InjectiveDay7PersistenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.state_path = Path(self.tmpdir.name) / "injectivelens_state.json"
        self.original_store = server_module.STATE_STORE
        self.original_latest = server_module.LATEST_ASSESSMENT
        self.original_records = dict(PROOF_STORE.records)
        self.original_proof_tx_hash = os.environ.get("INJECTIVE_PROOF_TX_HASH")
        os.environ["INJECTIVE_PROOF_TX_HASH"] = "C" * 64
        server_module.STATE_STORE = JsonStateStore(self.state_path)
        server_module.LATEST_ASSESSMENT = None
        PROOF_STORE.records.clear()

    def tearDown(self) -> None:
        server_module.STATE_STORE = self.original_store
        server_module.LATEST_ASSESSMENT = self.original_latest
        PROOF_STORE.records.clear()
        PROOF_STORE.records.update(self.original_records)
        self._restore_env("INJECTIVE_PROOF_TX_HASH", self.original_proof_tx_hash)
        self.tmpdir.cleanup()

    def test_latest_assessment_and_verified_proof_survive_restart_reload(self) -> None:
        with self._server() as first:
            assessment = first.post(
                "/api/injective/preflight",
                {
                    "prompt": "Open a 10x long INJ-PERP using 60% of available margin.",
                    "address": DEFAULT_ACCOUNT,
                    "network": "injective_testnet",
                    "mode": "demo_scenario",
                },
            )
            recorded = first.post(
                "/api/proof/record",
                {
                    "assessmentId": assessment["assessmentId"],
                    "assessmentHash": assessment["assessmentHash"],
                    "network": "injective_testnet",
                    "confirmation": "user_confirmed_record_assessment",
                },
            )
            verified = first.post(
                "/api/proof/verify",
                {
                    "assessmentHash": assessment["assessmentHash"],
                    "txHash": recorded["txHash"],
                    "network": "injective_testnet",
                },
            )
            self.assertEqual(verified["status"], "verified_matched")
            self.assertTrue(self.state_path.exists())

        server_module.LATEST_ASSESSMENT = None
        PROOF_STORE.records.clear()
        server_module.reload_state()

        with self._server() as second:
            health = second.get("/api/health")
            self.assertTrue(health["hasLatestAssessment"])
            self.assertEqual(Path(health["stateFile"]), self.state_path)

            history = second.get("/api/history/preflight")
            self.assertEqual(history["records"][0]["assessmentId"], assessment["assessmentId"])
            self.assertEqual(history["records"][0]["proofStatus"], "Proof verified · recorded hash matches")
            self.assertEqual(history["records"][0]["txHash"], recorded["txHash"])

            audit = second.get(f"/api/agent/audit?assessmentId={assessment['assessmentId']}")
            self.assertTrue(any(event["tool"] == "VerifyAssessment" and event["status"] == "completed" for event in audit["toolTrace"]))

    def test_json_state_store_round_trips_latest_and_proof_records(self) -> None:
        store = JsonStateStore(self.state_path)
        assessment = {"assessmentId": "a1", "assessmentHash": "0xabc", "proof": {"status": "recorded"}}
        proof = {"assessmentHash": "0xabc", "status": "recorded", "recordedAssessmentHash": "0xabc"}
        store.save_latest_assessment(assessment)
        store.save_proof_record(proof)

        reloaded = JsonStateStore(self.state_path)
        self.assertEqual(reloaded.get_latest_assessment(), assessment)
        self.assertEqual(reloaded.get_proof_records()["0xabc"], proof)

    def _server(self) -> "_ServerHarness":
        return _ServerHarness()

    @staticmethod
    def _restore_env(key: str, value: str | None) -> None:
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


class _ServerHarness:
    def __enter__(self) -> "_ServerHarness":
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), InjectiveLensRequestHandler)
        self.server.quiet = True  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return self

    def __exit__(self, *_args: object) -> None:
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()

    def post(self, path: str, body: dict[str, object]) -> dict[str, object]:
        request = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.opener.open(request, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))

    def get(self, path: str) -> dict[str, object]:
        with self.opener.open(self.base_url + path, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
