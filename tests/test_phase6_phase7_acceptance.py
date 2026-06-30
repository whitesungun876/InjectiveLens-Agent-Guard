from __future__ import annotations

import json
import threading
import unittest
from urllib import request

from backend.mantlelens.server import create_server
from backend.mantlelens.workflows import WalletGuardRunner


class Phase7EnhancementApiTest(unittest.TestCase):
    def setUp(self) -> None:
        package = WalletGuardRunner().scan_wallet(fixture_id="critical_wallet", include_explanation=False)
        self.payload = {
            "assessment": package["assessment"],
            "evidence": package["evidenceBundle"]["evidence"],
            "coverage": package["coverage"],
            "toolOutputs": package["toolOutputs"],
            "history": package.get("history"),
            "inventory": package.get("inventory"),
        }

    def test_each_phase7_module_has_api_output_fallback_and_safety(self) -> None:
        server = create_server("127.0.0.1", 0, quiet=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        opener = request.build_opener(request.ProxyHandler({}))
        try:
            host, port = server.server_address
            base = f"http://{host}:{port}"
            endpoints = {
                "nft": "/api/nft/approvals",
                "revoke": "/api/revoke/prepare",
                "defi": "/api/defi/positions",
                "goplus": "/api/security/goplus-full",
                "tx": "/api/simulation/transaction",
                "share": "/api/social/share-card",
                "reputation": "/api/reputation/feedback",
                "summary": "/api/enhancements",
            }
            responses = {name: self._post_json(opener, base + path, self.payload) for name, path in endpoints.items()}
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(responses["nft"]["module"], "nft_approval_detection")
        self.assertTrue(responses["nft"]["fallbackUsed"])
        self.assertIn(responses["nft"]["status"], {"available", "unavailable"})

        revoke = responses["revoke"]
        self.assertEqual(revoke["module"], "manual_revoke")
        self.assertEqual(revoke["status"], "manual_signature_required")
        self.assertFalse(revoke["broadcasted"])
        self.assertFalse(revoke["transactionCreated"])
        self.assertTrue(revoke["safety"]["serverDoesNotSign"])
        self.assertTrue(revoke["txRequest"]["data"].startswith("0x095ea7b3"))

        self.assertEqual(responses["defi"]["module"], "defi_deep_parsing")
        self.assertIn("fallbackUsed", responses["defi"])

        goplus = responses["goplus"]
        self.assertEqual(goplus["module"], "goplus_full_security")
        self.assertEqual(goplus["status"], "available")
        self.assertTrue(goplus["approvalSignals"])
        self.assertIn("advisory", " ".join(goplus["limitations"]).lower())

        tx = responses["tx"]
        self.assertEqual(tx["module"], "real_tx_simulation")
        self.assertFalse(tx["transactionCreated"])
        self.assertFalse(tx["broadcasted"])
        self.assertTrue(tx["fallbackUsed"])

        share = responses["share"]
        self.assertEqual(share["module"], "social_share_card")
        self.assertFalse(share["posted"])
        self.assertIn("Not financial advice", share["card"]["disclaimer"])

        reputation = responses["reputation"]
        self.assertEqual(reputation["module"], "erc8004_reputation_feedback")
        self.assertEqual(reputation["status"], "local_recorded")
        self.assertFalse(reputation["onchainSubmitted"])

        summary = responses["summary"]
        self.assertEqual(summary["moduleCount"], 7)
        self.assertTrue(summary["safety"]["noAutoRevoke"])

    def test_nft_approval_detection_accepts_real_payload_not_file_presence(self) -> None:
        payload = {
            "nftApprovals": [
                {
                    "tokenStandard": "ERC721",
                    "tokenAddress": "0x1111111111111111111111111111111111111111",
                    "operator": "0x2222222222222222222222222222222222222222",
                    "isActive": True,
                    "evidenceIds": ["ev_nft_approval"],
                    "txHash": "0xnftapproval",
                }
            ]
        }
        server = create_server("127.0.0.1", 0, quiet=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        opener = request.build_opener(request.ProxyHandler({}))
        try:
            host, port = server.server_address
            response = self._post_json(opener, f"http://{host}:{port}/api/nft/approvals", payload)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(response["status"], "available")
        self.assertEqual(response["activeApprovalCount"], 1)
        self.assertEqual(response["items"][0]["tokenStandard"], "ERC721")

    def _post_json(self, opener, url: str, payload: dict) -> dict:
        req = request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with opener.open(req, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
