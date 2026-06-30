from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from backend.mantlelens.alerts import SQLiteAlertStore
from backend.mantlelens.config import MantleLensConfig
from backend.mantlelens.enhancements import simulate_transaction
from backend.mantlelens.inventory import HistoryPageOptions
from backend.mantlelens.live_adapters import EtherscanV2Client, GoPlusClient, NFT_APPROVAL_FOR_ALL_TOPIC0
from backend.mantlelens.onchain import AssessmentRecorderConfig
from backend.mantlelens.trend import SQLiteTrendStore


WALLET = "0x1234567890abcdef1234567890abcdef12345678"
TOKEN = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
OPERATOR = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


class FakeSimulationHttp:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def post_json(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        self.calls.append({"url": url, "payload": payload, "timeout": timeout})
        return self.response


class FakeEtherscanHttp:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 8,
    ) -> dict[str, Any]:
        params = params or {}
        self.calls.append(dict(params))
        self.assert_nft_approval_query(params)
        page = int(params["page"])
        rows = [
            {
                "address": TOKEN,
                "topics": [
                    NFT_APPROVAL_FOR_ALL_TOPIC0,
                    "0x" + WALLET[2:].rjust(64, "0"),
                    "0x" + OPERATOR[2:].rjust(64, "0"),
                ],
                "data": "0x1",
                "transactionHash": f"0xnftapproval{page}_{index}",
                "blockNumber": str(500 + page),
                "logIndex": str(index),
            }
            for index in range(10)
        ]
        return {"status": "1", "message": "OK", "result": rows if page == 1 else []}

    def assert_nft_approval_query(self, params: dict[str, Any]) -> None:
        if params.get("module") != "logs":
            raise AssertionError(params)
        if params.get("action") != "getLogs":
            raise AssertionError(params)
        if params.get("topic0") != NFT_APPROVAL_FOR_ALL_TOPIC0:
            raise AssertionError(params)
        if params.get("topic1") != "0x" + WALLET[2:].rjust(64, "0"):
            raise AssertionError(params)


class FakeGoPlusHttp:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 8,
    ) -> dict[str, Any]:
        self.calls.append({"url": url, "params": params or {}, "headers": headers or {}})
        if "/address_security/" in url:
            return {"result": {"blacklist_doubt": "1", "data_source": "mock"}}
        if "/token_approval_security/" in url:
            return {"result": {WALLET: [{"spender_address": OPERATOR, "token_address": TOKEN, "is_open_source": "0"}]}}
        raise AssertionError(url)


class Phase9ProductionReadinessTest(unittest.TestCase):
    def test_assessment_logger_address_alias_is_supported(self) -> None:
        address = "0x" + "a" * 40
        with patch.dict(
            "os.environ",
            {
                "ASSESSMENT_CONTRACT_ADDRESS": "",
                "ASSESSMENT_LOGGER_ADDRESS": address,
                "PRIVATE_KEY": "",
                "WALLET_PRIVATE_KEY": "",
            },
            clear=False,
        ):
            cfg = MantleLensConfig.from_env()
            recorder_cfg = AssessmentRecorderConfig.from_env()

        self.assertEqual(cfg.assessment_contract_address, address)
        self.assertEqual(recorder_cfg.contract_address, address)

    def test_sqlite_trend_persists_across_store_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "state.sqlite3")
            first = SQLiteTrendStore(db_path)
            first.record_assessment(_assessment("a1", score=12), {"evidenceBundleHash": "0xe1"})

            second = SQLiteTrendStore(db_path)
            trend = second.record_assessment(_assessment("a2", score=28), {"evidenceBundleHash": "0xe2"})

        self.assertEqual(trend["source"], "sqlite_assessment_history")
        self.assertEqual(trend["status"], "available")
        self.assertEqual(trend["pointCount"], 2)
        self.assertEqual(trend["delta"]["scoreDelta"], 16.0)

    def test_sqlite_alert_resolution_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "state.sqlite3")
            first = SQLiteAlertStore(db_path)
            alerts = first.evaluate(
                assessment={
                    **_assessment("alerted", score=70),
                    "topRisks": [
                        {
                            "riskId": "risk_active_approval",
                            "type": "approval",
                            "severity": "High",
                            "claimText": "Active approval needs review.",
                            "evidenceIds": ["ev_approval"],
                        }
                    ],
                },
                evidence_bundle={"evidence": [{"evidenceId": "ev_approval"}]},
                coverage={"dataCompleteness": {}, "sourceAvailability": {}},
                inventory=None,
                history=None,
                trend=None,
            )
            alert_id = alerts[0]["alertId"]

            second = SQLiteAlertStore(db_path)
            resolved = second.resolve(alert_id=alert_id, resolution_note="phase9")
            resolved_list = second.list_alerts(status="resolved")

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["status"], "resolved")
        self.assertTrue(any(item["alertId"] == alert_id for item in resolved_list))

    def test_transaction_simulation_calls_configured_provider_without_broadcast(self) -> None:
        http = FakeSimulationHttp({"result": {"success": True, "gasUsed": "0x5208", "assetChanges": []}})
        config = MantleLensConfig(
            tx_simulation_rpc_url="mock://tenderly",
            tx_simulation_provider="tenderly_rpc",
        )
        result = simulate_transaction(
            {
                "assessment": {"wallet": {"address": WALLET}},
                "txRequest": {
                    "chainId": 5000,
                    "to": TOKEN,
                    "data": "0x095ea7b3" + OPERATOR[2:].rjust(64, "0") + "0" * 64,
                    "value": "0x0",
                },
            },
            config=config,
            http=http,
        )

        self.assertEqual(result["status"], "simulated")
        self.assertEqual(result["provider"], "tenderly_rpc")
        self.assertFalse(result["transactionCreated"])
        self.assertFalse(result["broadcasted"])
        self.assertFalse(result["fallbackUsed"])
        self.assertEqual(http.calls[0]["payload"]["method"], "tenderly_simulateTransaction")
        self.assertEqual(http.calls[0]["payload"]["params"][0]["from"], WALLET)

    def test_transaction_simulation_provider_error_is_unknown_not_safe(self) -> None:
        result = simulate_transaction(
            {
                "assessment": {"wallet": {"address": WALLET}},
                "txRequest": {"chainId": 5000, "to": TOKEN, "data": "0x1234", "value": "0x0"},
            },
            config=MantleLensConfig(tx_simulation_rpc_url="mock://tenderly"),
            http=FakeSimulationHttp({"error": {"code": -32000, "message": "simulation failed"}}),
        )

        self.assertEqual(result["status"], "provider_error")
        self.assertTrue(result["fallbackUsed"])
        self.assertIn("unknown, not safe", " ".join(result["limitations"]))
        self.assertFalse(result["transactionCreated"])
        self.assertFalse(result["broadcasted"])

    def test_alchemy_transaction_simulation_uses_flat_execution_params(self) -> None:
        http = FakeSimulationHttp({"result": {"calls": [], "logs": [], "revertReason": None}})
        result = simulate_transaction(
            {
                "assessment": {"wallet": {"address": WALLET}},
                "txRequest": {"chainId": 5003, "to": TOKEN, "data": "0x1234", "value": "0x0"},
            },
            config=MantleLensConfig(
                chain_id=5003,
                tx_simulation_rpc_url="mock://alchemy",
                tx_simulation_provider="alchemy_rpc",
                tx_simulation_rpc_method="alchemy_simulateExecution",
            ),
            http=http,
        )

        self.assertEqual(result["status"], "simulated")
        self.assertFalse(result["broadcasted"])
        self.assertEqual(http.calls[0]["payload"]["method"], "alchemy_simulateExecution")
        self.assertEqual(http.calls[0]["payload"]["params"][0], "FLAT")
        self.assertEqual(http.calls[0]["payload"]["params"][1]["from"], WALLET)
        self.assertEqual(http.calls[0]["payload"]["params"][2], "latest")

    def test_nft_approval_for_all_logs_are_paginated(self) -> None:
        http = FakeEtherscanHttp()
        client = EtherscanV2Client(
            MantleLensConfig(etherscan_v2_api_key="mock_key"),
            http,  # type: ignore[arg-type]
        )
        result = client.nft_approval_for_all_logs_paginated(
            WALLET,
            HistoryPageOptions(page_size=10, max_pages=2, from_block=1, to_block="latest"),
        )

        self.assertEqual(result.rows[0]["transactionHash"], "0xnftapproval1_0")
        self.assertEqual(result.page_info["fetchedPages"], 2)
        self.assertEqual(http.calls[0]["topic0"], NFT_APPROVAL_FOR_ALL_TOPIC0)

    def test_goplus_full_security_clients_use_address_and_approval_endpoints(self) -> None:
        http = FakeGoPlusHttp()
        client = GoPlusClient(
            MantleLensConfig(goplus_api_key="mock_goplus", chain_id=5000),
            http,  # type: ignore[arg-type]
        )

        address = client.address_security(WALLET)
        approval = client.approval_security(WALLET)

        self.assertEqual(address["blacklist_doubt"], "1")
        self.assertTrue(approval[WALLET])
        self.assertIn("/api/v1/address_security/", http.calls[0]["url"])
        self.assertEqual(http.calls[0]["params"]["chain_id"], 5000)
        self.assertIn("/api/v2/token_approval_security/5000", http.calls[1]["url"])
        self.assertEqual(http.calls[1]["params"]["addresses"], WALLET)
        self.assertEqual(http.calls[1]["headers"]["Authorization"], "Bearer mock_goplus")


def _assessment(assessment_id: str, *, score: float) -> dict[str, Any]:
    return {
        "wallet": {"walletHash": "0xwallet_phase9", "address": WALLET},
        "assessmentId": assessment_id,
        "timestamp": f"2026-06-08T00:00:0{assessment_id[-1]}Z",
        "walletRiskScore": score,
        "riskLevel": "High" if score >= 50 else "Low",
        "dataConfidence": 0.8,
        "dataStatus": "COMPLETE",
        "dataMode": "live",
        "chainId": 5000,
        "assessmentHash": f"0xassessment_{assessment_id}",
        "topRisks": [{"riskId": "risk_a"}],
    }


if __name__ == "__main__":
    unittest.main()
