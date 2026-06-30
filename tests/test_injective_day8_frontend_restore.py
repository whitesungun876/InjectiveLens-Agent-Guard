from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from backend.injectivelens.fixtures import DEFAULT_ACCOUNT
from backend.injectivelens.persistence import JsonStateStore
from backend.injectivelens.proof import PROOF_STORE
from backend.injectivelens.server import InjectiveLensRequestHandler
import backend.injectivelens.server as server_module


class InjectiveDay8FrontendRestoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.state_path = Path(self.tmpdir.name) / "injectivelens_state.json"
        self.original_store = server_module.STATE_STORE
        self.original_latest = server_module.LATEST_ASSESSMENT
        self.original_records = dict(PROOF_STORE.records)
        self.original_proof_tx_hash = os.environ.get("INJECTIVE_PROOF_TX_HASH")
        os.environ["INJECTIVE_PROOF_TX_HASH"] = "D" * 64
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

    def test_latest_endpoint_returns_404_until_an_assessment_exists(self) -> None:
        with self._server() as harness:
            status, payload = harness.get_status("/api/injective/preflight/latest")
            self.assertEqual(status, 404)
            self.assertEqual(payload["error"], "not_found")

    def test_latest_endpoint_restores_verified_assessment_after_reload(self) -> None:
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

        server_module.LATEST_ASSESSMENT = None
        PROOF_STORE.records.clear()
        server_module.reload_state()

        with self._server() as second:
            latest = second.get("/api/injective/preflight/latest")
            self.assertEqual(latest["assessmentId"], assessment["assessmentId"])
            self.assertEqual(latest["assessmentHash"], assessment["assessmentHash"])
            self.assertEqual(latest["proof"]["status"], "verified_matched")
            self.assertEqual(latest["proof"]["txHash"], recorded["txHash"])

            health = second.get("/api/health")
            self.assertGreaterEqual(int(str(health["day"])), 8)
            self.assertTrue(health["hasLatestAssessment"])

    def test_frontend_restores_latest_assessment_on_page_load(self) -> None:
        app_source = Path("frontend/app/src/App.tsx").read_text()
        api_source = Path("frontend/app/src/injectivePreflightApi.ts").read_text()

        self.assertIn("useEffect", app_source)
        self.assertIn("getLatestPreflightAssessment", app_source)
        self.assertIn("Restoring latest pre-flight check", app_source)
        self.assertIn("/api/injective/preflight/latest", api_source)
        self.assertIn("response.status === 404", api_source)

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
        status, payload = self.get_status(path)
        if status >= 400:
            raise AssertionError(f"GET {path} failed with {status}: {payload}")
        return payload

    def get_status(self, path: str) -> tuple[int, dict[str, object]]:
        try:
            with self.opener.open(self.base_url + path, timeout=3) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read().decode("utf-8"))
            finally:
                exc.close()


if __name__ == "__main__":
    unittest.main()
