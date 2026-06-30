from __future__ import annotations

import json
import os
import threading
import unittest
from unittest.mock import patch
from urllib import error, request

from backend.mantlelens.chain_targets import (
    ChainTargetError,
    config_for_chain_target,
    resolve_chain_target,
)
from backend.mantlelens.config import MantleLensConfig
from backend.mantlelens.server import create_server


WALLET = "0x000000000000000000000000000000000000dEaD"


class ChainTargetRegistryTest(unittest.TestCase):
    def test_provider_status_exposes_public_chain_targets_without_secrets(self) -> None:
        rpc_secret = "sensitive-rpc-token"
        with patch.dict(
            os.environ,
            {
                "MANTLE_CHAIN_ID": "5003",
                "MANTLE_RPC_URL": f"https://example.invalid/{rpc_secret}",
                "ASSESSMENT_CONTRACT_ADDRESS": "0x88507ca2ebcf3c3469fbd6b1085b01b6c147c06c",
                "WALLET_PRIVATE_KEY": "do-not-leak",
            },
            clear=True,
        ):
            status = MantleLensConfig.from_env().public_provider_status()

        targets = {target["id"]: target for target in status["chainTargets"]}
        self.assertEqual(status["defaultTargetId"], "mantle-sepolia")
        self.assertEqual(targets["mantle-sepolia"]["chainId"], 5003)
        self.assertEqual(targets["mantle-sepolia"]["label"], "Mantle Sepolia · Testnet · 5003")
        self.assertTrue(targets["mantle-sepolia"]["enabled"])
        self.assertTrue(targets["mantle-sepolia"]["supportsReadOnlyScan"])
        self.assertIn("Recommended for demo", targets["mantle-sepolia"]["description"])
        self.assertFalse(targets["custom-evm"]["enabled"])
        self.assertTrue(targets["custom-evm"]["comingSoon"])

        rendered = json.dumps(status, sort_keys=True)
        self.assertNotIn(rpc_secret, rendered)
        self.assertNotIn("do-not-leak", rendered)
        self.assertNotIn("rpc_url", rendered)

    def test_resolve_target_validates_chain_id_and_disabled_target(self) -> None:
        config = MantleLensConfig(chain_id=5003, mantle_rpc_url="mock://mantle-sepolia")

        target = resolve_chain_target(config, target_id="mantle-sepolia", chain_id=5003)
        self.assertEqual(target.id, "mantle-sepolia")
        self.assertEqual(target.chain_id, 5003)

        with self.assertRaises(ChainTargetError):
            resolve_chain_target(config, target_id="mantle-sepolia", chain_id=5000)
        with self.assertRaises(ChainTargetError):
            resolve_chain_target(config, target_id="custom-evm", chain_id=None)

    def test_config_for_target_pins_adapter_chain_without_exposing_rpc(self) -> None:
        config = MantleLensConfig(chain_id=5003, mantle_rpc_url="mock://mantle-sepolia")
        target = resolve_chain_target(config, target_id="mantle-sepolia", chain_id=5003)

        adapter_config = config_for_chain_target(config, target)

        self.assertEqual(adapter_config.chain_id, 5003)
        self.assertEqual(adapter_config.network_name, "Mantle Sepolia")
        self.assertEqual(adapter_config.effective_rpc_url, "mock://mantle-sepolia")

    def test_live_scan_endpoint_validates_target_id_and_chain_id_before_provider_calls(self) -> None:
        with patch.dict(
            os.environ,
            {
                "MANTLE_CHAIN_ID": "5003",
                "MANTLE_RPC_URL": "mock://mantle-sepolia",
            },
            clear=True,
        ):
            server = create_server("127.0.0.1", 0, quiet=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                payload = {
                    "dataMode": "live",
                    "scanMode": "live",
                    "walletAddress": WALLET,
                    "targetId": "mantle-sepolia",
                    "chainId": 5000,
                }
                req = request.Request(
                    f"http://{host}:{port}/api/wallet/scan",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                opener = request.build_opener(request.ProxyHandler({}))
                with self.assertRaises(error.HTTPError) as ctx:
                    opener.open(req, timeout=5)
                body = json.loads(ctx.exception.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(ctx.exception.code, 400)
        self.assertEqual(body["error"], "bad_request")
        self.assertIn("chainId mismatch", body["message"])


if __name__ == "__main__":
    unittest.main()
