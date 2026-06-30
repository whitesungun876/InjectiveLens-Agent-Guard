from __future__ import annotations

import unittest

from backend.injectivelens.adapters import InjectiveAdapterConfig, LiveInjectiveReadOnlyAdapter
from backend.injectivelens.fixtures import DEFAULT_ACCOUNT, DEFAULT_SUBACCOUNT_ID, build_preflight_assessment


class FakeHttpClient:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def get_json(self, url: str) -> dict[str, object]:
        self.urls.append(url)
        if "/balances/" in url:
            return {"balances": [{"denom": "inj", "amount": "125000000000000000000"}]}
        if "/market/" in url:
            return {
                "market": {
                    "marketId": "live-inj-perp",
                    "markPrice": "25.1",
                    "oraclePrice": "25.0",
                    "spreadBps": "12",
                    "fundingRatePct": "0.01",
                    "maxLeverage": "20",
                }
            }
        if "/positions/" in url:
            return {
                "positions": [
                    {
                        "market": "INJ-PERP",
                        "side": "long",
                        "notionalUsd": 800,
                        "leverage": 2,
                        "liquidationPrice": 14.0,
                        "liquidationDistancePct": 44.0,
                        "unrealizedPnlUsd": 3.5,
                    }
                ]
            }
        raise AssertionError(f"unexpected url {url}")


class InjectiveDay4AdapterTest(unittest.TestCase):
    def test_live_account_adapter_reads_configured_lcd_endpoint(self) -> None:
        client = FakeHttpClient()
        adapter = LiveInjectiveReadOnlyAdapter(
            config=InjectiveAdapterConfig(lcd_rest_url="https://injective-lcd.test"),
            http_client=client,  # type: ignore[arg-type]
        )
        account = adapter.account_state(DEFAULT_ACCOUNT, DEFAULT_SUBACCOUNT_ID, "injective_testnet", "live_read_only")
        self.assertEqual(account["sourceCoverage"]["status"], "full")
        self.assertEqual(account["balances"][0]["source"], "Injective LCD read-only")
        self.assertIn("/cosmos/bank/v1beta1/balances/", client.urls[0])
        self.assertEqual(account["evidence"][0]["mode"], "live_read_only")

    def test_live_unconfigured_sources_are_partial_and_block_safe_prompt(self) -> None:
        adapter = LiveInjectiveReadOnlyAdapter(config=InjectiveAdapterConfig())
        assessment = build_preflight_assessment(
            {
                "prompt": "Open a 2x long INJ-PERP using 10% of available margin.",
                "address": DEFAULT_ACCOUNT,
                "network": "injective_testnet",
                "mode": "live_read_only",
            },
            adapter=adapter,
        )
        self.assertEqual(assessment["sourceCoverage"]["status"], "partial")
        self.assertIn("unknown", assessment["sourceCoverage"]["explanation"].lower())
        self.assertEqual(assessment["decision"]["decision"], "block")
        self.assertTrue(any(risk["id"] == "risk_coverage" for risk in assessment["decision"]["topRisks"]))
        serialized = str(assessment)
        self.assertNotIn("INJECTIVE_LCD_REST_URL", serialized)
        self.assertNotIn("INJECTIVE_MARKET_SNAPSHOT_URL", serialized)
        self.assertNotIn("INJECTIVE_POSITIONS_URL", serialized)
        self.assertIn("Live account adapter unavailable", serialized)
        self.assertIn("Live market source unavailable", serialized)
        self.assertIn("Live positions source unavailable", serialized)

    def test_live_configured_sources_preserve_low_risk_allow_path(self) -> None:
        client = FakeHttpClient()
        adapter = LiveInjectiveReadOnlyAdapter(
            config=InjectiveAdapterConfig(
                lcd_rest_url="https://injective-lcd.test",
                market_snapshot_url="https://injective-indexer.test/market/{market}",
                positions_url="https://injective-indexer.test/positions/{subaccount_id}",
            ),
            http_client=client,  # type: ignore[arg-type]
        )
        assessment = build_preflight_assessment(
            {
                "prompt": "Open a 2x long INJ-PERP using 10% of available margin.",
                "address": DEFAULT_ACCOUNT,
                "network": "injective_testnet",
                "mode": "live_read_only",
            },
            adapter=adapter,
        )
        self.assertEqual(assessment["sourceCoverage"]["status"], "full")
        self.assertEqual(assessment["decision"]["decision"], "allow")
        self.assertEqual(assessment["evidence"][1]["mode"], "live_read_only")
        self.assertGreaterEqual(len(client.urls), 3)

    def test_live_market_adapter_parses_official_lcd_market_shape(self) -> None:
        class OfficialLcdMarketClient:
            def get_json(self, url: str) -> dict[str, object]:
                return {
                    "market": {
                        "market": {
                            "ticker": "INJ/USDC PERP",
                            "market_id": "0xdc70164d7120529c3cd84278c98df4151210c0447a65a2aab03459cf328de41e",
                            "initial_margin_ratio": "0.033333000000000000",
                            "quote_decimals": 6,
                        },
                        "perpetual_info": {
                            "market_info": {
                                "market_id": "0xdc70164d7120529c3cd84278c98df4151210c0447a65a2aab03459cf328de41e",
                                "hourly_interest_rate": "0.000004166660000000",
                            }
                        },
                        "mark_price": "4705677.515392310308000000",
                    }
                }

        adapter = LiveInjectiveReadOnlyAdapter(
            config=InjectiveAdapterConfig(market_snapshot_url="https://lcd.test/injective/exchange/v1beta1/derivative/markets/inj"),
            http_client=OfficialLcdMarketClient(),  # type: ignore[arg-type]
        )
        market = adapter.market_snapshot("INJ-PERP", "injective_testnet", "live_read_only")
        self.assertEqual(market["sourceCoverage"]["status"], "full")
        self.assertEqual(market["sourceKind"], "live_read_only")
        self.assertEqual(market["marketId"], "0xdc70164d7120529c3cd84278c98df4151210c0447a65a2aab03459cf328de41e")
        self.assertAlmostEqual(market["markPrice"], 4.70567751539231)
        self.assertAlmostEqual(market["maxLeverage"], 30.0, places=1)


if __name__ == "__main__":
    unittest.main()
