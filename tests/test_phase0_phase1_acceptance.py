from __future__ import annotations

import json
import threading
import unittest
from pathlib import Path
from urllib import request

from backend.mantlelens.ledger import LEDGER
from backend.mantlelens.server import create_server


ROOT = Path(__file__).resolve().parents[1]


class Phase0ScopeTest(unittest.TestCase):
    def test_p1_acceptance_scope_distinguishes_foundation_from_full(self) -> None:
        document = ROOT / "docs" / "P1_ACCEPTANCE_SCOPE.md"
        text = document.read_text()

        self.assertIn("P1-foundation", text)
        self.assertIn("P1-full", text)
        self.assertIn("Phase 1 API Contract", text)
        self.assertIn("Missing indexed data is unknown, not safe", text)


class Phase1ApiCompletionTest(unittest.TestCase):
    def setUp(self) -> None:
        LEDGER.records.clear()
        LEDGER.idempotency.clear()

    def test_prd_standalone_apis_return_documented_payloads(self) -> None:
        server = create_server("127.0.0.1", 0, quiet=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        opener = request.build_opener(request.ProxyHandler({}))
        try:
            host, port = server.server_address
            base = f"http://{host}:{port}"
            query = "?fixtureId=high_risk_wallet&dataMode=demo"

            balances = self._get_json(opener, f"{base}/api/wallet/balances{query}")
            approvals = self._get_json(opener, f"{base}/api/wallet/approvals{query}")
            transfers = self._get_json(opener, f"{base}/api/wallet/transfers{query}")
            exposure = self._get_json(opener, f"{base}/api/wallet/exposure{query}")
            availability = self._get_json(opener, f"{base}/api/wallet/data-availability{query}")
            risk = self._post_json(
                opener,
                f"{base}/api/risk/evaluate-wallet",
                {"fixtureId": "high_risk_wallet", "dataMode": "demo"},
            )
            outcome = self._post_json(
                opener,
                f"{base}/api/assessment/outcome",
                {
                    "assessmentId": risk["assessment"]["assessmentId"],
                    "outcomeHash": "0xphase1_outcome_hash",
                    "userResponse": "reviewed",
                    "idempotencyKey": "idem_phase1_outcome",
                    "traceId": "trace_phase1_outcome",
                },
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertTrue(balances["balances"])
        self.assertTrue(approvals["approvals"])
        self.assertTrue(transfers["transfers"])
        self.assertGreater(exposure["portfolioExposure"]["totalWalletValueUsd"], 0)
        self.assertFalse(availability["missingDataIsSafe"])
        self.assertEqual(risk["assessment"]["schemaVersion"], "mantlelens.wallet_assessment.v1")
        self.assertTrue(risk["evidenceBundle"]["evidence"])
        self.assertEqual(outcome["record"]["outcomeStatus"], "recorded")
        self.assertEqual(outcome["record"]["outcomeHash"], "0xphase1_outcome_hash")
        self.assertFalse(outcome["record"]["realExecutionAllowed"])

    def _get_json(self, opener, url: str) -> dict:
        with opener.open(url, timeout=5) as response:
            self.assertEqual(response.status, 200)
            return json.loads(response.read().decode("utf-8"))

    def _post_json(self, opener, url: str, payload: dict) -> dict:
        req = request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with opener.open(req, timeout=5) as response:
            self.assertIn(response.status, {200, 202})
            return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()

