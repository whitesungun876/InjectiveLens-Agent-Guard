from __future__ import annotations

import json
import threading
import unittest
from urllib import error, request

from backend.mantlelens.alerts import ALERT_STORE, InMemoryAlertStore
from backend.mantlelens.config import KnownToken, MantleLensConfig
from backend.mantlelens.inventory import HistoryPageOptions, PaginatedHistoryResult, TokenInventoryNormalizer
from backend.mantlelens.live_adapters import EtherscanV2Client, LiveWalletAdapter
from backend.mantlelens.server import create_server
from backend.mantlelens.trend import TREND_STORE, InMemoryTrendStore
from backend.mantlelens.workflows import WalletGuardRunner


WALLET = "0x1234567890abcdef1234567890abcdef12345678"
TOKEN = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
SPENDER = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


class FakeRpc:
    def native_balance(self, wallet_address: str) -> int:
        self._assert_wallet(wallet_address)
        return 12 * 10**18

    def erc20_balance_of(self, token_address: str, wallet_address: str) -> int:
        self._assert_wallet(wallet_address)
        self.assert_token(token_address)
        return 1000 * 10**6

    def erc20_allowance(self, token_address: str, owner: str, spender: str) -> int:
        self._assert_wallet(owner)
        self.assert_token(token_address)
        self.assert_spender(spender)
        return 2**256 - 1

    def _assert_wallet(self, wallet_address: str) -> None:
        if wallet_address.lower() != WALLET:
            raise AssertionError(wallet_address)

    def assert_token(self, token_address: str) -> None:
        if token_address.lower() != TOKEN:
            raise AssertionError(token_address)

    def assert_spender(self, spender: str) -> None:
        if spender.lower() != SPENDER:
            raise AssertionError(spender)


class FakeGoPlus:
    def token_security(self, token_addresses: list[str]) -> dict:
        return {TOKEN: {"is_honeypot": "0", "is_blacklisted": "0"}}


class FakeMoralis:
    def wallet_tokens(self, wallet_address: str) -> list[dict]:
        return [
            {
                "token_address": TOKEN,
                "symbol": "USDT",
                "decimals": 6,
                "balance": str(1000 * 10**6),
                "usd_price": "1",
                "usd_value": "1000",
            }
        ]


class FakeEtherscan:
    def __init__(self) -> None:
        self.approval_options: list[HistoryPageOptions] = []
        self.transfer_options: list[HistoryPageOptions] = []

    def approval_logs_paginated(self, owner_address: str, options: HistoryPageOptions | None = None) -> PaginatedHistoryResult:
        page_options = options or HistoryPageOptions()
        self.approval_options.append(page_options)
        rows = self.approval_logs(owner_address)
        return PaginatedHistoryResult(rows=rows, page_info=page_options.page_info(fetched_pages=1, last_page_count=len(rows), row_count=len(rows)))

    def approval_logs(self, owner_address: str) -> list[dict]:
        return [
            {
                "address": TOKEN,
                "topics": [
                    "0x8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925",
                    "0x" + WALLET[2:].rjust(64, "0"),
                    "0x" + SPENDER[2:].rjust(64, "0"),
                ],
                "data": hex(2**256 - 1),
                "transactionHash": "0xapprovalhash",
                "blockNumber": "100",
                "logIndex": "1",
            }
        ]

    def token_transfers_paginated(self, wallet_address: str, options: HistoryPageOptions | None = None) -> PaginatedHistoryResult:
        page_options = options or HistoryPageOptions()
        self.transfer_options.append(page_options)
        rows = self.token_transfers(wallet_address)
        return PaginatedHistoryResult(rows=rows, page_info=page_options.page_info(fetched_pages=1, last_page_count=len(rows), row_count=len(rows)))

    def token_transfers(self, wallet_address: str, *, limit: int = 100) -> list[dict]:
        return [
            {
                "hash": "0xtransferhash",
                "from": "0x1234569999999999999999999999999999995678",
                "to": WALLET,
                "contractAddress": TOKEN,
                "tokenName": "Tether USD",
                "tokenSymbol": "USDT",
                "tokenDecimal": "6",
                "value": "1",
                "blockNumber": "101",
                "logIndex": "2",
                "timeStamp": "1780000000",
            }
        ]


class FakeHttp:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def get_json(self, url: str, *, params: dict | None = None, headers: dict | None = None, timeout: float = 8) -> dict:
        params = params or {}
        self.calls.append(dict(params))
        if params.get("action") == "tokentx":
            page = int(params["page"])
            if page == 1:
                rows = [
                    {
                        "hash": f"0xpage1_{index}",
                        "contractAddress": TOKEN,
                        "tokenSymbol": "USDT",
                        "tokenDecimal": "6",
                        "blockNumber": str(100 + index),
                        "logIndex": str(index),
                    }
                    for index in range(10)
                ]
            else:
                rows = [
                    {
                        "hash": "0xpage2_0",
                        "contractAddress": TOKEN,
                        "tokenSymbol": "USDT",
                        "tokenDecimal": "6",
                        "blockNumber": "200",
                        "logIndex": "0",
                    }
                ]
            return {"status": "1", "message": "OK", "result": rows}
        if params.get("action") == "getLogs":
            page = int(params["page"])
            if page == 1:
                rows = [
                    {
                        "transactionHash": f"0xapproval_page1_{index}",
                        "address": TOKEN,
                        "logIndex": str(index),
                        "blockNumber": str(300 + index),
                    }
                    for index in range(10)
                ]
            else:
                rows = [
                    {
                        "transactionHash": "0xapproval_page2_0",
                        "address": TOKEN,
                        "logIndex": "0",
                        "blockNumber": "400",
                    }
                ]
            return {"status": "1", "message": "OK", "result": rows}
        return {"status": "1", "message": "OK", "result": []}


class P1LiveDataFoundationTest(unittest.TestCase):
    def test_live_adapter_scan_is_evidence_bound_and_simulation_only(self) -> None:
        config = MantleLensConfig(
            mantle_rpc_url="mock://mantle",
            moralis_api_key="mock_moralis",
            moralis_data_api_enabled=True,
            etherscan_v2_api_key="mock_etherscan",
            known_tokens=(KnownToken("USDT", TOKEN, 6, 1.0),),
        )
        adapter = LiveWalletAdapter(
            config=config,
            rpc=FakeRpc(),
            goplus=FakeGoPlus(),
            moralis=FakeMoralis(),
            etherscan=FakeEtherscan(),
        )
        runner = WalletGuardRunner(adapter=adapter)
        response = runner.scan_wallet(fixture_id="live_wallet", wallet_address=WALLET)
        assessment = response["assessment"]

        self.assertEqual(assessment["dataMode"], "live")
        self.assertEqual(assessment["chainId"], 5000)
        self.assertIn(assessment["riskLevel"], {"High", "Critical"})
        self.assertEqual(assessment["dataCompleteness"]["fullTokenInventory"], "available")
        self.assertTrue(response["evidenceBundle"]["evidence"])
        for risk in assessment["topRisks"]:
            self.assertTrue(risk["evidenceIds"])
        self.assertIsNotNone(response["inventory"])
        self.assertIsNotNone(response["history"])

        simulation = runner.simulate(assessment, simulation_type="approval_revoke_impact")
        self.assertEqual(simulation["simulation"]["executionMode"], "simulation_only")
        self.assertFalse(simulation["simulation"]["transactionCreated"])

    def test_transfer_derived_inventory_confirms_current_balance_with_rpc(self) -> None:
        config = MantleLensConfig(
            mantle_rpc_url="mock://mantle",
            etherscan_v2_api_key="mock_etherscan",
        )
        fake_etherscan = FakeEtherscan()
        adapter = LiveWalletAdapter(
            config=config,
            rpc=FakeRpc(),
            goplus=FakeGoPlus(),
            etherscan=fake_etherscan,
        )
        history_options = HistoryPageOptions(page_size=25, max_pages=2, from_block=50, to_block=150)
        response = WalletGuardRunner(adapter=adapter).scan_wallet(
            fixture_id="live_wallet",
            wallet_address=WALLET,
            history_options=history_options,
        )
        inventory = response["inventory"]
        self.assertEqual(inventory["source"], "etherscan_v2_candidates_rpc_balanceOf")
        self.assertEqual(inventory["inventoryStatus"], "partial")
        self.assertTrue(any(item["tokenAddress"] == TOKEN for item in inventory["tokens"]))
        token = next(item for item in inventory["tokens"] if item["tokenAddress"] == TOKEN)
        self.assertEqual(token["balanceRaw"], str(1000 * 10**6))
        self.assertEqual(token["balanceSource"], "mantle_rpc_balanceOf")
        self.assertTrue(token["evidenceIds"])
        self.assertIn("tokenInventoryCandidates", response["coverage"]["pageCoverage"])
        self.assertEqual(response["coverage"]["pageCoverage"]["tokenInventoryCandidates"]["pageSize"], 25)
        self.assertEqual(response["coverage"]["pageCoverage"]["approvalHistory"]["fromBlock"], 50)
        self.assertEqual(response["coverage"]["pageCoverage"]["transferHistory"]["toBlock"], 150)
        self.assertEqual(fake_etherscan.transfer_options[0].max_pages, 2)
        self.assertEqual(fake_etherscan.approval_options[0].page_size, 25)

    def test_token_inventory_normalizer_dedupes_candidates(self) -> None:
        normalizer = TokenInventoryNormalizer(wallet=WALLET, chain_id=5000)
        candidates = normalizer.token_candidates_from_transfer_rows(
            [
                {
                    "contractAddress": TOKEN.upper(),
                    "tokenSymbol": "USDT",
                    "tokenName": "Tether USD",
                    "tokenDecimal": "6",
                    "blockNumber": "10",
                    "hash": "0xold",
                },
                {
                    "contractAddress": TOKEN,
                    "tokenSymbol": "USDT",
                    "tokenDecimal": "6",
                    "blockNumber": "20",
                    "hash": "0xnew",
                },
            ]
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["tokenAddress"], TOKEN)
        self.assertEqual(candidates[0]["firstSeenBlock"], 10)
        self.assertEqual(candidates[0]["lastSeenBlock"], 20)

    def test_etherscan_v2_paginated_transfers_use_page_and_offset(self) -> None:
        http = FakeHttp()
        client = EtherscanV2Client(
            MantleLensConfig(etherscan_v2_api_key="mock_etherscan"),
            http,
        )
        result = client.token_transfers_paginated(
            WALLET,
            HistoryPageOptions(page_size=10, max_pages=2),
        )
        self.assertEqual(len(result.rows), 11)
        self.assertEqual(result.page_info["fetchedPages"], 2)
        self.assertFalse(result.page_info["hasMore"])
        self.assertEqual([call["page"] for call in http.calls], [1, 2])
        self.assertEqual([call["offset"] for call in http.calls], [10, 10])

    def test_etherscan_v2_paginated_approvals_use_page_offset_and_blocks(self) -> None:
        http = FakeHttp()
        client = EtherscanV2Client(
            MantleLensConfig(etherscan_v2_api_key="mock_etherscan"),
            http,
        )
        result = client.approval_logs_paginated(
            WALLET,
            HistoryPageOptions(page_size=10, max_pages=2, from_block=123, to_block=456),
        )
        self.assertEqual(len(result.rows), 11)
        self.assertEqual(result.page_info["fromBlock"], 123)
        self.assertEqual(result.page_info["toBlock"], 456)
        self.assertEqual([call["page"] for call in http.calls], [1, 2])
        self.assertEqual([call["offset"] for call in http.calls], [10, 10])
        self.assertEqual([call["fromBlock"] for call in http.calls], [123, 123])
        self.assertEqual([call["toBlock"] for call in http.calls], [456, 456])

    def test_live_scan_requires_wallet_address_over_http(self) -> None:
        server = create_server("127.0.0.1", 0, quiet=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = server.server_address
            req = request.Request(
                f"http://{host}:{port}/api/wallet/scan",
                data=json.dumps({"dataMode": "live"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            opener = request.build_opener(request.ProxyHandler({}))
            with self.assertRaises(error.HTTPError) as ctx:
                opener.open(req, timeout=5)
            payload = json.loads(ctx.exception.read().decode("utf-8"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(ctx.exception.code, 400)
        self.assertEqual(payload["error"], "bad_request")

    def test_http_scan_rejects_invalid_history_options(self) -> None:
        server = create_server("127.0.0.1", 0, quiet=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = server.server_address
            req = request.Request(
                f"http://{host}:{port}/api/wallet/scan",
                data=json.dumps(
                    {
                        "dataMode": "live",
                        "walletAddress": WALLET,
                        "historyOptions": {"pageSize": 9},
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            opener = request.build_opener(request.ProxyHandler({}))
            with self.assertRaises(error.HTTPError) as ctx:
                opener.open(req, timeout=5)
            payload = json.loads(ctx.exception.read().decode("utf-8"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(ctx.exception.code, 400)
        self.assertEqual(payload["error"], "bad_request")
        self.assertIn("historyOptions", payload["message"])

    def test_risk_trend_first_and_second_scan_are_hash_bound(self) -> None:
        trend_store = InMemoryTrendStore()
        first = WalletGuardRunner(trend_store=trend_store).scan_wallet(
            fixture_id="high_risk_wallet",
        )
        first_trend = first["trend"]

        self.assertEqual(first_trend["status"], "insufficient_history")
        self.assertEqual(first_trend["pointCount"], 1)
        self.assertEqual(first_trend["points"][0]["assessmentHash"], first["assessment"]["assessmentHash"])
        self.assertEqual(
            first_trend["points"][0]["evidenceBundleHash"],
            first["evidenceBundle"]["evidenceBundleHash"],
        )

        second = WalletGuardRunner(trend_store=trend_store).scan_wallet(
            fixture_id="high_risk_wallet",
        )
        second_trend = second["trend"]

        self.assertEqual(second_trend["status"], "available")
        self.assertEqual(second_trend["pointCount"], 2)
        self.assertEqual(second_trend["delta"]["scoreDelta"], 0.0)
        self.assertFalse(second_trend["delta"]["riskLevelChanged"])
        self.assertIn(
            "risk_trend_recorded",
            [event["eventType"] for event in second["trace"]["events"]],
        )

    def test_trend_store_reports_score_delta_and_new_top_risks(self) -> None:
        trend_store = InMemoryTrendStore()
        base = {
            "wallet": {"walletHash": "0xwallet_hash_trend_test"},
            "assessmentId": "assessment_trend_1",
            "timestamp": "2026-06-08T00:00:00+00:00",
            "walletRiskScore": 40,
            "riskLevel": "Moderate",
            "dataConfidence": 0.72,
            "dataStatus": "PARTIAL_OR_UNKNOWN",
            "dataMode": "demo",
            "chainId": 5000,
            "assessmentHash": "0xassessment_trend_1",
            "topRisks": [{"riskId": "risk_existing"}],
        }
        trend_store.record_assessment(base, {"evidenceBundleHash": "0xevidence_trend_1"})
        current = {
            **base,
            "assessmentId": "assessment_trend_2",
            "timestamp": "2026-06-08T00:01:00+00:00",
            "walletRiskScore": 65,
            "riskLevel": "High",
            "dataConfidence": 0.82,
            "assessmentHash": "0xassessment_trend_2",
            "topRisks": [{"riskId": "risk_existing"}, {"riskId": "risk_new_active_approval"}],
        }
        trend = trend_store.record_assessment(current, {"evidenceBundleHash": "0xevidence_trend_2"})

        self.assertEqual(trend["status"], "available")
        self.assertEqual(trend["delta"]["scoreDelta"], 25.0)
        self.assertEqual(trend["delta"]["dataConfidenceDelta"], 0.1)
        self.assertTrue(trend["delta"]["riskLevelChanged"])
        self.assertEqual(trend["delta"]["newTopRiskIds"], ["risk_new_active_approval"])
        self.assertEqual(trend["points"][1]["evidenceBundleHash"], "0xevidence_trend_2")
        self.assertTrue(trend["points"][1]["trendPointHash"].startswith("0x"))

    def test_alerts_detect_risk_sources_and_suppress_duplicates(self) -> None:
        trend_store = InMemoryTrendStore()
        alert_store = InMemoryAlertStore()
        first = WalletGuardRunner(
            trend_store=trend_store,
            alert_store=alert_store,
        ).scan_wallet(fixture_id="high_risk_wallet")
        first_alerts = first["alerts"]
        first_types = {alert["alertType"] for alert in first_alerts}

        self.assertIn("new_active_approval", first_types)
        self.assertIn("suspicious_transfer_detected", first_types)
        self.assertIn("source_unavailable", first_types)
        for alert in first_alerts:
            self.assertEqual(alert["status"], "open")
            self.assertTrue(alert["sourceAssessmentHash"].startswith("0x"))
            self.assertTrue(alert["evidenceIds"] or alert["sourceAssessmentHash"])

        second = WalletGuardRunner(
            trend_store=trend_store,
            alert_store=alert_store,
        ).scan_wallet(fixture_id="high_risk_wallet")
        first_by_type = {alert["alertType"]: alert for alert in first_alerts}
        second_by_type = {alert["alertType"]: alert for alert in second["alerts"]}

        self.assertEqual(
            second_by_type["new_active_approval"]["alertId"],
            first_by_type["new_active_approval"]["alertId"],
        )
        self.assertEqual(second_by_type["new_active_approval"]["occurrenceCount"], 2)
        self.assertIn(
            "alerts_evaluated",
            [event["eventType"] for event in second["trace"]["events"]],
        )

    def test_alert_store_emits_trend_and_token_security_alerts(self) -> None:
        alert_store = InMemoryAlertStore()
        evidence_bundle = {
            "evidenceBundleHash": "0xevidence_bundle_alerts",
            "evidence": [
                {
                    "evidenceId": "ev_token_security",
                    "type": "token_security",
                }
            ],
        }
        assessment = {
            "wallet": {"walletHash": "0xwallet_hash_alerts"},
            "assessmentId": "assessment_alerts_2",
            "assessmentHash": "0xassessment_alerts_2",
            "walletRiskScore": 65,
            "riskLevel": "High",
            "dataMode": "demo",
            "topRisks": [],
        }
        trend = {
            "status": "available",
            "delta": {
                "scoreDelta": 25.0,
                "riskLevelChanged": True,
                "previousRiskLevel": "Moderate",
                "currentRiskLevel": "High",
                "previousAssessmentHash": "0xassessment_alerts_1",
                "currentAssessmentHash": "0xassessment_alerts_2",
            },
        }
        alerts = alert_store.evaluate(
            assessment=assessment,
            evidence_bundle=evidence_bundle,
            coverage={"dataCompleteness": {}, "sourceAvailability": {}},
            inventory={
                "tokens": [
                    {
                        "symbol": "RISK",
                        "tokenAddress": TOKEN,
                        "securityStatus": "risky",
                        "evidenceIds": ["ev_token_security"],
                    }
                ]
            },
            history=None,
            trend=trend,
        )
        alert_types = {alert["alertType"] for alert in alerts}

        self.assertIn("risk_score_increased", alert_types)
        self.assertIn("risk_level_increased", alert_types)
        self.assertIn("token_security_risky", alert_types)
        token_alert = next(alert for alert in alerts if alert["alertType"] == "token_security_risky")
        self.assertEqual(token_alert["evidenceIds"], ["ev_token_security"])
        self.assertEqual(token_alert["severity"], "High")

    def test_http_history_alerts_and_resolve_api(self) -> None:
        TREND_STORE.reset()
        ALERT_STORE.reset()
        server = create_server("127.0.0.1", 0, quiet=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        opener = request.build_opener(request.ProxyHandler({}))
        try:
            host, port = server.server_address
            scan_url = f"http://{host}:{port}/api/wallet/scan"
            scan_body = json.dumps(
                {
                    "dataMode": "demo",
                    "fixtureId": "high_risk_wallet",
                    "includeExplanation": False,
                }
            ).encode("utf-8")
            headers = {"Content-Type": "application/json"}
            scans = []
            for _ in range(2):
                req = request.Request(scan_url, data=scan_body, headers=headers, method="POST")
                with opener.open(req, timeout=5) as response:
                    scans.append(json.loads(response.read().decode("utf-8")))
            wallet_hash = scans[-1]["assessment"]["wallet"]["walletHash"]
            history_url = f"http://{host}:{port}/api/wallet/history?walletHash={wallet_hash}"
            with opener.open(history_url, timeout=5) as response:
                history_payload = json.loads(response.read().decode("utf-8"))
            alerts_url = f"http://{host}:{port}/api/alerts?walletHash={wallet_hash}&status=open"
            with opener.open(alerts_url, timeout=5) as response:
                alerts_payload = json.loads(response.read().decode("utf-8"))

            self.assertEqual(history_payload["trend"]["status"], "available")
            self.assertGreaterEqual(history_payload["trend"]["pointCount"], 2)
            self.assertGreaterEqual(len(alerts_payload["alerts"]), 1)
            alert_id = alerts_payload["alerts"][0]["alertId"]

            resolve_req = request.Request(
                f"http://{host}:{port}/api/alerts/resolve",
                data=json.dumps({"alertId": alert_id, "resolutionNote": "HTTP smoke"}).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with opener.open(resolve_req, timeout=5) as response:
                resolved_payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(resolved_payload["alert"]["status"], "resolved")
            self.assertEqual(resolved_payload["alert"]["resolutionNote"], "HTTP smoke")

            with opener.open(f"http://{host}:{port}/api/alerts?walletHash={wallet_hash}&status=resolved", timeout=5) as response:
                resolved_list = json.loads(response.read().decode("utf-8"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            TREND_STORE.reset()
            ALERT_STORE.reset()

        self.assertTrue(any(alert["alertId"] == alert_id for alert in resolved_list["alerts"]))


if __name__ == "__main__":
    unittest.main()
