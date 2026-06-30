from __future__ import annotations

import json
import time
import unittest
from unittest.mock import patch

from backend.mantlelens.config import MantleLensConfig
from backend.mantlelens.live_adapters import JsonHttpClient, LiveWalletAdapter
from backend.mantlelens.workflows import WalletGuardRunner

from tests.test_p1_live_data_foundation import FakeEtherscan, FakeGoPlus, FakeMoralis, FakeRpc, TOKEN, WALLET


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class SlowNativeRpc:
    def native_balance(self, wallet_address: str) -> int:
        time.sleep(0.02)
        return 1

    def erc20_balance_of(self, token_address: str, wallet_address: str) -> int:
        raise AssertionError("deadline should skip ERC20 balance checks")

    def erc20_allowance(self, token_address: str, owner: str, spender: str) -> int:
        raise AssertionError("deadline should skip allowance checks")


class TimeoutRpc:
    def native_balance(self, wallet_address: str) -> int:
        raise TimeoutError("Mantle RPC timed out")

    def erc20_balance_of(self, token_address: str, wallet_address: str) -> int:
        raise TimeoutError("Mantle RPC timed out")

    def erc20_allowance(self, token_address: str, owner: str, spender: str) -> int:
        raise TimeoutError("Mantle RPC timed out")


class Phase4LiveDataStabilityTest(unittest.TestCase):
    def test_json_http_client_retries_transient_timeout(self) -> None:
        calls = []

        def fake_urlopen(req, timeout):
            calls.append(timeout)
            if len(calls) == 1:
                raise TimeoutError("temporary provider timeout")
            return FakeResponse({"status": "1", "result": []})

        client = JsonHttpClient(timeout=0.01, retries=1, retry_backoff=0)
        with patch("backend.mantlelens.live_adapters.request.urlopen", side_effect=fake_urlopen):
            payload = client.get_json("https://example.test/api")

        self.assertEqual(payload["status"], "1")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls, [0.01, 0.01])

    def test_live_scan_deadline_skips_remaining_tools_without_hanging(self) -> None:
        config = MantleLensConfig(
            mantle_rpc_url="mock://mantle",
            live_scan_deadline_sec=0.01,
            live_request_timeout_sec=0.5,
            live_request_retries=0,
        )
        adapter = LiveWalletAdapter(config=config, rpc=SlowNativeRpc())

        started = time.perf_counter()
        response = WalletGuardRunner(adapter=adapter).scan_wallet(
            fixture_id="live_wallet",
            wallet_address=WALLET,
            include_explanation=False,
        )
        duration = time.perf_counter() - started

        self.assertLess(duration, 1)
        tool_outputs = response["toolOutputs"]
        self.assertEqual(tool_outputs["getNativeBalance"]["sourceStatus"], "available")
        self.assertEqual(tool_outputs["getKnownTokenBalances"]["sourceStatus"], "unavailable")
        self.assertIn(
            "tool_call_skipped",
            [event["eventType"] for event in response["trace"]["events"]],
        )
        self.assertEqual(response["coverage"]["sourceAvailability"]["mantleRpc"]["status"], "partial")

    def test_provider_timeout_marks_source_partial_not_safe(self) -> None:
        config = MantleLensConfig(mantle_rpc_url="mock://mantle")
        adapter = LiveWalletAdapter(config=config, rpc=TimeoutRpc())

        response = WalletGuardRunner(adapter=adapter).scan_wallet(
            fixture_id="live_wallet",
            wallet_address=WALLET,
            include_explanation=False,
        )

        self.assertEqual(response["toolOutputs"]["getNativeBalance"]["sourceStatus"], "unavailable")
        self.assertEqual(response["coverage"]["sourceAvailability"]["mantleRpc"]["status"], "partial")
        self.assertEqual(response["assessment"]["dataStatus"], "PARTIAL_OR_UNKNOWN")
        self.assertNotEqual(response["assessment"]["riskLevel"], "Low")

    def test_moralis_balances_and_history_switches_are_explicit(self) -> None:
        disabled = MantleLensConfig(moralis_api_key="mock_moralis")
        enabled = MantleLensConfig(
            moralis_api_key="mock_moralis",
            moralis_balances_enabled=True,
            moralis_history_enabled=True,
        )

        self.assertFalse(disabled.moralis_balances_available)
        self.assertFalse(disabled.moralis_history_available)
        self.assertEqual(disabled.source_snapshot()["moralis"]["status"], "unavailable")
        self.assertTrue(enabled.moralis_balances_available)
        self.assertTrue(enabled.moralis_history_available)
        self.assertEqual(enabled.source_snapshot()["moralis"]["status"], "available")


class Phase5EvidenceRiskSchemaTest(unittest.TestCase):
    def test_assessment_metric_results_and_evidence_schema_are_contract_aligned(self) -> None:
        response = WalletGuardRunner().scan_wallet(
            fixture_id="high_risk_wallet",
            include_explanation=False,
        )
        assessment = response["assessment"]
        evidence = response["evidenceBundle"]["evidence"]

        self.assertEqual(len(assessment["metricResults"]), 5)
        self.assertEqual(
            round(sum(metric["weightedContribution"] for metric in assessment["metricResults"]), 2),
            assessment["walletRiskScore"],
        )
        for metric in assessment["metricResults"]:
            self.assertIn(metric["metricId"], assessment["subScores"])
            self.assertEqual(metric["score"], assessment["subScores"][metric["metricId"]])
            self.assertTrue(metric["evidenceIds"])

        for risk in assessment["topRisks"]:
            self.assertTrue(risk["evidenceIds"])
        for action in assessment["suggestedActions"]:
            self.assertTrue(action["evidenceIds"])

        approval_evidence = [item for item in evidence if item["type"] == "approval"]
        transfer_evidence = [item for item in evidence if item["type"] == "transfer"]
        self.assertTrue(approval_evidence)
        self.assertTrue(all(isinstance(item.get("allowanceConfirmed"), bool) for item in approval_evidence))
        self.assertTrue(transfer_evidence)
        self.assertTrue(all(item.get("txHash") for item in transfer_evidence))

    def test_live_approval_evidence_marks_rpc_allowance_confirmation(self) -> None:
        config = MantleLensConfig(
            mantle_rpc_url="mock://mantle",
            moralis_api_key="mock_moralis",
            moralis_balances_enabled=True,
            etherscan_v2_api_key="mock_etherscan",
        )
        adapter = LiveWalletAdapter(
            config=config,
            rpc=FakeRpc(),
            goplus=FakeGoPlus(),
            moralis=FakeMoralis(),
            etherscan=FakeEtherscan(),
        )
        response = WalletGuardRunner(adapter=adapter).scan_wallet(
            fixture_id="live_wallet",
            wallet_address=WALLET,
            include_explanation=False,
        )

        approvals = response["toolOutputs"]["getTokenApprovals"]["output"]["approvals"]
        approval_evidence = [
            item for item in response["evidenceBundle"]["evidence"]
            if item["type"] == "approval"
        ]
        self.assertTrue(approvals)
        self.assertTrue(all(item["allowanceConfirmed"] for item in approvals))
        self.assertTrue(all(item["allowanceConfirmed"] for item in approval_evidence))

    def test_goplus_clean_result_is_signal_not_safety_claim(self) -> None:
        config = MantleLensConfig(
            mantle_rpc_url="mock://mantle",
            moralis_api_key="mock_moralis",
            moralis_balances_enabled=True,
            etherscan_v2_api_key="mock_etherscan",
        )
        adapter = LiveWalletAdapter(
            config=config,
            rpc=FakeRpc(),
            goplus=FakeGoPlus(),
            moralis=FakeMoralis(),
            etherscan=FakeEtherscan(),
        )
        response = WalletGuardRunner(adapter=adapter).scan_wallet(
            fixture_id="live_wallet",
            wallet_address=WALLET,
            include_explanation=False,
        )

        security_evidence = [
            item for item in response["evidenceBundle"]["evidence"]
            if item["type"] == "token_security"
        ]
        self.assertTrue(security_evidence)
        for item in security_evidence:
            text = item["claimText"].lower()
            self.assertNotIn("guaranteed", text)
            self.assertNotIn("safe", text)
            self.assertIn("signal", item["limitation"].lower())
            self.assertEqual(item["rawData"]["riskFlags"], [])
        self.assertEqual(response["coverage"]["sourceAvailability"]["goPlus"]["status"], "available")


if __name__ == "__main__":
    unittest.main()
