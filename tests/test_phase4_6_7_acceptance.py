from __future__ import annotations

import json
import os
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

from backend.injectivelens.fixtures import DEFAULT_ACCOUNT, build_preflight_assessment, history_records
from backend.injectivelens.proof import PROOF_STORE
from backend.injectivelens.server import InjectiveLensRequestHandler


LOW_PROMPT = "Open a 2x long INJ-PERP using 10% of available margin."
MEDIUM_PROMPT = "Open a 4x long INJ-PERP using 25% of available margin."
CRITICAL_PROMPT = "Open a 10x long INJ-PERP using 60% of available margin."


class Phase467AcceptanceTest(unittest.TestCase):
    def test_phase4_demo_scenarios_return_approve_review_and_block(self) -> None:
        scenarios = {
            "approve": (LOW_PROMPT, "allow", "low"),
            "review": (MEDIUM_PROMPT, "warn", "moderate"),
            "block": (CRITICAL_PROMPT, "block", "critical"),
        }

        seen_decisions = set()
        for label, (prompt, expected_decision, expected_level) in scenarios.items():
            with self.subTest(label=label):
                assessment = build_preflight_assessment(
                    {
                        "prompt": prompt,
                        "address": DEFAULT_ACCOUNT,
                        "network": "injective_testnet",
                        "mode": "demo_scenario",
                    }
                )
                seen_decisions.add(assessment["decision"]["decision"])
                self.assertEqual(assessment["decision"]["decision"], expected_decision)
                self.assertEqual(assessment["decision"]["riskLevel"], expected_level)
                self.assertEqual(assessment["sourceCoverage"]["status"], "replay")
                self.assertEqual(assessment["sourceCoverage"]["modeSummary"], "Demo replay fixture")
                self.assertEqual(assessment["proof"]["status"], "ready_to_record")

        self.assertEqual(seen_decisions, {"allow", "warn", "block"})

    def test_phase6_history_records_keep_demo_live_and_proof_status_distinct(self) -> None:
        low = build_preflight_assessment(
            {"prompt": LOW_PROMPT, "address": DEFAULT_ACCOUNT, "network": "injective_testnet", "mode": "demo_scenario"}
        )
        medium = build_preflight_assessment(
            {"prompt": MEDIUM_PROMPT, "address": DEFAULT_ACCOUNT, "network": "injective_testnet", "mode": "demo_scenario"}
        )
        critical = build_preflight_assessment(
            {"prompt": CRITICAL_PROMPT, "address": DEFAULT_ACCOUNT, "network": "injective_testnet", "mode": "demo_scenario"}
        )
        live = build_preflight_assessment(
            {"prompt": CRITICAL_PROMPT, "address": DEFAULT_ACCOUNT, "network": "injective_testnet", "mode": "live_read_only"}
        )
        live["proof"] = {
            **live["proof"],
            "status": "verified_matched",
            "txHash": "0x" + "c" * 64,
            "recordedAssessmentHash": live["assessmentHash"],
        }

        records = history_records(live, [critical, medium, low])
        decisions = [record["decision"] for record in records]
        self.assertEqual(decisions[:4], ["block", "block", "warn", "allow"])
        self.assertEqual(records[0]["dataMode"], "live_read_only")
        self.assertTrue(records[0]["proofVerified"])
        self.assertTrue(records[0]["txHash"].startswith("0x"))
        for record in records[1:4]:
            self.assertEqual(record["dataMode"], "demo_replay")
            self.assertEqual(record["sourceMode"], "Demo replay fixture")
            self.assertFalse(record["proofRecorded"])
            self.assertIsNone(record["txHash"])

    def test_phase7_http_judge_path_records_three_decision_classes_and_verified_proof(self) -> None:
        old_tx = os.environ.get("INJECTIVE_PROOF_TX_HASH")
        old_height = os.environ.get("INJECTIVE_PROOF_BLOCK_HEIGHT")
        os.environ["INJECTIVE_PROOF_TX_HASH"] = "0x" + "d" * 64
        os.environ["INJECTIVE_PROOF_BLOCK_HEIGHT"] = "131957156"
        PROOF_STORE.records.clear()
        try:
            with _ServerHarness() as harness:
                low = harness.preflight(LOW_PROMPT, "demo_scenario")
                medium = harness.preflight(MEDIUM_PROMPT, "demo_scenario")
                critical = harness.preflight(CRITICAL_PROMPT, "live_read_only")
                recorded = harness.post(
                    "/api/proof/record",
                    {
                        "assessmentId": critical["assessmentId"],
                        "assessmentHash": critical["assessmentHash"],
                        "network": "injective_testnet",
                        "confirmation": "user_confirmed_record_assessment",
                    },
                )
                verified = harness.post(
                    "/api/proof/verify",
                    {
                        "assessmentHash": critical["assessmentHash"],
                        "txHash": recorded["txHash"],
                        "network": "injective_testnet",
                    },
                )
                history = harness.get("/api/history/preflight")["records"]
                audit = harness.get(f"/api/agent/audit?assessmentId={critical['assessmentId']}")

            self.assertEqual(low["decision"]["decision"], "allow")
            self.assertEqual(medium["decision"]["decision"], "warn")
            self.assertEqual(critical["decision"]["decision"], "block")
            self.assertEqual(recorded["status"], "recorded")
            self.assertEqual(verified["status"], "verified_matched")
            self.assertGreaterEqual(len(audit["toolTrace"]), 12)
            self.assertEqual({record["decision"] for record in history[:3]}, {"allow", "warn", "block"})
            self.assertEqual(history[0]["proofStatus"], "Proof verified \u00b7 recorded hash matches")
            self.assertEqual(history[0]["dataMode"], "live_read_only")
            self.assertTrue(history[0]["simulatedMarket"])
            self.assertNotIn("demo_fixture", json.dumps(history, sort_keys=True))
        finally:
            self._restore_env("INJECTIVE_PROOF_TX_HASH", old_tx)
            self._restore_env("INJECTIVE_PROOF_BLOCK_HEIGHT", old_height)
            PROOF_STORE.records.clear()

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

    def preflight(self, prompt: str, mode: str) -> dict[str, object]:
        return self.post(
            "/api/injective/preflight",
            {
                "prompt": prompt,
                "address": DEFAULT_ACCOUNT,
                "subaccountId": "0x0000000000000000000000000000000000000000000000000000000000000000",
                "network": "injective_testnet",
                "mode": mode,
            },
        )

    def get(self, path: str) -> dict[str, object]:
        with self.opener.open(self.base_url + path, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))

    def post(self, path: str, body: dict[str, object]) -> dict[str, object]:
        request = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.opener.open(request, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
