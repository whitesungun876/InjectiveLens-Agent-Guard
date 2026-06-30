from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from .fixtures import (
    SIMULATED_FIXTURE_PREFIX,
    account_state_fixture,
    market_snapshot_fixture,
    positions_fixture,
    subaccount_kind,
)


class InjectiveReadOnlyAdapter(Protocol):
    def account_state(self, address: str, subaccount_id: str, network: str, mode: str) -> dict[str, Any]:
        ...

    def market_snapshot(self, market: str, network: str, mode: str) -> dict[str, Any]:
        ...

    def positions(self, subaccount_id: str, network: str, mode: str) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class InjectiveAdapterConfig:
    lcd_rest_url: str | None = None
    market_snapshot_url: str | None = None
    positions_url: str | None = None
    timeout_seconds: float = 3.0

    @classmethod
    def from_env(cls) -> "InjectiveAdapterConfig":
        return cls(
            lcd_rest_url=_clean_url(os.getenv("INJECTIVE_LCD_REST_URL")),
            market_snapshot_url=_clean_url(os.getenv("INJECTIVE_MARKET_SNAPSHOT_URL")),
            positions_url=_clean_url(os.getenv("INJECTIVE_POSITIONS_URL")),
            timeout_seconds=float(os.getenv("INJECTIVE_READ_TIMEOUT_SECONDS") or "3"),
        )


class JsonHttpClient:
    def __init__(self, timeout_seconds: float = 3.0) -> None:
        self.timeout_seconds = timeout_seconds
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get_json(self, url: str) -> dict[str, Any]:
        request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
        with self.opener.open(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))


class FixtureInjectiveReadOnlyAdapter:
    def account_state(self, address: str, subaccount_id: str, network: str, mode: str) -> dict[str, Any]:
        return account_state_fixture(address, subaccount_id, network, mode)

    def market_snapshot(self, market: str, network: str, mode: str) -> dict[str, Any]:
        return market_snapshot_fixture(market, network, mode)

    def positions(self, subaccount_id: str, network: str, mode: str) -> dict[str, Any]:
        return positions_fixture(subaccount_id, network, mode)


class LiveInjectiveReadOnlyAdapter:
    """Read-only adapter for live Injective sources.

    Day 4 intentionally avoids SDK signing surfaces. Endpoints are configurable
    because public Injective gateways vary by provider. Missing or failing
    sources become partial coverage instead of silently becoming safe.
    """

    def __init__(
        self,
        config: InjectiveAdapterConfig | None = None,
        http_client: JsonHttpClient | None = None,
        fallback: FixtureInjectiveReadOnlyAdapter | None = None,
    ) -> None:
        self.config = config or InjectiveAdapterConfig.from_env()
        self.http_client = http_client or JsonHttpClient(self.config.timeout_seconds)
        self.fallback = fallback or FixtureInjectiveReadOnlyAdapter()

    def account_state(self, address: str, subaccount_id: str, network: str, mode: str) -> dict[str, Any]:
        fallback = self.fallback.account_state(address, subaccount_id, network, mode)
        if not self.config.lcd_rest_url:
            return _partial_fallback(
                fallback,
                source_name="Injective LCD account balances",
                reason="Live account adapter unavailable",
                evidence_id="ev_account_001",
            )
        try:
            url = f"{self.config.lcd_rest_url.rstrip('/')}/cosmos/bank/v1beta1/balances/{urllib.parse.quote(address)}"
            data = self.http_client.get_json(url)
            balances = [
                {
                    "denom": str(item.get("denom") or "unknown"),
                    "amount": str(item.get("amount") or "0"),
                    "source": "Injective LCD read-only",
                }
                for item in data.get("balances", [])
                if isinstance(item, dict)
            ]
            return {
                "network": network,
                "address": address,
                "subaccountId": subaccount_id,
                "subaccountKind": subaccount_kind(subaccount_id),
                "sourceKind": "live_read_only",
                "adapter": "LiveInjectiveReadOnlyAdapter",
                "sourceDisclosure": "Live Injective LCD balance read; no signing or order placement.",
                "balances": balances,
                "sourceCoverage": _coverage(
                    "full",
                    explanation="Injective LCD account balances were read successfully.",
                    sources=[{"name": "Injective LCD account balances", "status": "available"}],
                ),
                "evidence": [
                    {
                        "id": "ev_account_001",
                        "source": "Injective account state",
                        "claim": f"Read {len(balances)} account balance rows from Injective LCD.",
                        "mode": "live_read_only",
                        "verification": "GET /cosmos/bank/v1beta1/balances/{address}",
                        "dataQuality": "Live read-only",
                        "adapter": "LiveInjectiveReadOnlyAdapter",
                        "sourceKind": "live_read_only",
                        "scope": "account_state",
                        "timestamp": fallback["evidence"][0]["timestamp"],
                        "rawRef": "injective:lcd:balances",
                    }
                ],
            }
        except Exception as exc:  # noqa: BLE001 - exact provider errors vary.
            return _partial_fallback(
                fallback,
                source_name="Injective LCD account balances",
                reason=f"Injective LCD read failed: {exc.__class__.__name__}",
                evidence_id="ev_account_001",
            )

    def market_snapshot(self, market: str, network: str, mode: str) -> dict[str, Any]:
        fallback = self.fallback.market_snapshot(market, network, mode)
        if not self.config.market_snapshot_url:
            return _partial_fallback(
                fallback,
                source_name="Injective market snapshot endpoint",
                reason="Live market source unavailable",
                evidence_id="ev_market_001",
            )
        try:
            data = self.http_client.get_json(_format_url(self.config.market_snapshot_url, market=market, network=network))
            market_data = _unwrap_market_payload(data, market)
            mark_price = _scaled_market_number(
                _first_number(market_data, ["markPrice", "mark_price", "mark_price_chain", "price", "oraclePrice", "oracle_price"]),
                market_data,
            )
            oracle_price = _scaled_market_number(_first_number(market_data, ["oraclePrice", "oracle_price"]), market_data)
            max_leverage = _market_max_leverage(market_data)
            market_id = str(market_data.get("marketId") or market_data.get("market_id") or "")
            source_kind = "live_read_only" if _looks_like_live_market_id(market_id) else "live_read_only_simulated_market_id"
            source_status = "available" if source_kind == "live_read_only" else "partial"
            return {
                **fallback,
                "marketId": market_id if source_kind == "live_read_only" else f"{SIMULATED_FIXTURE_PREFIX}:{market}",
                "sourceKind": source_kind,
                "adapter": "LiveInjectiveReadOnlyAdapter",
                "sourceDisclosure": (
                    "Live Injective market endpoint returned a market id."
                    if source_kind == "live_read_only"
                    else "Live endpoint returned price context but not a real Injective market id; simulated market id is disclosed."
                ),
                "markPrice": mark_price or fallback["markPrice"],
                "oraclePrice": oracle_price or mark_price or fallback["oraclePrice"],
                "spreadBps": _first_number(market_data, ["spreadBps", "spread_bps"]) or fallback["spreadBps"],
                "fundingRatePct": _market_funding_rate_pct(market_data) or fallback["fundingRatePct"],
                "maxLeverage": max_leverage or fallback["maxLeverage"],
                "sourceCoverage": _coverage(
                    "full" if source_kind == "live_read_only" else "partial",
                    unknown=[] if source_kind == "live_read_only" else ["real Injective market id"],
                    explanation=(
                        "Injective market snapshot endpoint was read successfully."
                        if source_kind == "live_read_only"
                        else "Injective market endpoint returned partial context; missing real market id is unknown, not safe."
                    ),
                    sources=[{"name": "Injective market snapshot", "status": source_status}],
                ),
                "evidence": [
                    {
                        "id": "ev_market_001",
                        "source": "Injective market snapshot",
                        "claim": f"{market} market snapshot was read from a configured Injective endpoint.",
                        "mode": "live_read_only",
                        "verification": "Configured read-only market endpoint",
                        "dataQuality": "Live read-only" if source_kind == "live_read_only" else "Partial live read; simulated market id",
                        "adapter": "LiveInjectiveReadOnlyAdapter",
                        "sourceKind": source_kind,
                        "scope": "market_context",
                        "timestamp": fallback["evidence"][0]["timestamp"],
                        "rawRef": "injective:market_snapshot",
                    }
                ],
            }
        except Exception as exc:  # noqa: BLE001
            return _partial_fallback(
                fallback,
                source_name="Injective market snapshot endpoint",
                reason=f"Injective market read failed: {exc.__class__.__name__}",
                evidence_id="ev_market_001",
            )

    def positions(self, subaccount_id: str, network: str, mode: str) -> dict[str, Any]:
        fallback = self.fallback.positions(subaccount_id, network, mode)
        if not self.config.positions_url:
            return _partial_fallback(
                fallback,
                source_name="Injective positions endpoint",
                reason="Live positions source unavailable",
                evidence_id="ev_position_001",
            )
        try:
            data = self.http_client.get_json(_format_url(self.config.positions_url, subaccount_id=subaccount_id, network=network))
            raw_positions = _unwrap_positions_payload(data)
            positions = [_normalize_position(item) for item in raw_positions if isinstance(item, dict)]
            return {
                "network": network,
                "subaccountId": subaccount_id,
                "subaccountKind": subaccount_kind(subaccount_id),
                "sourceKind": "live_read_only",
                "adapter": "LiveInjectiveReadOnlyAdapter",
                "sourceDisclosure": "Live Injective positions read through configured read-only endpoint.",
                "positions": positions,
                "sourceCoverage": _coverage(
                    "full",
                    explanation="Injective positions endpoint was read successfully.",
                    sources=[{"name": "Injective open positions", "status": "available"}],
                ),
                "evidence": [
                    {
                        "id": "ev_position_001",
                        "source": "Injective position model",
                        "claim": f"Read {len(positions)} open position rows from configured Injective endpoint.",
                        "mode": "live_read_only",
                        "verification": "Configured read-only positions endpoint",
                        "dataQuality": "Live read-only",
                        "adapter": "LiveInjectiveReadOnlyAdapter",
                        "sourceKind": "live_read_only",
                        "scope": "position_context",
                        "timestamp": fallback["evidence"][0]["timestamp"],
                        "rawRef": "injective:positions",
                    }
                ],
            }
        except Exception as exc:  # noqa: BLE001
            return _partial_fallback(
                fallback,
                source_name="Injective positions endpoint",
                reason=f"Injective positions read failed: {exc.__class__.__name__}",
                evidence_id="ev_position_001",
            )


def select_injective_adapter(mode: str) -> InjectiveReadOnlyAdapter:
    if mode == "live_read_only":
        return LiveInjectiveReadOnlyAdapter()
    return FixtureInjectiveReadOnlyAdapter()


def _partial_fallback(payload: dict[str, Any], source_name: str, reason: str, evidence_id: str) -> dict[str, Any]:
    cloned = json.loads(json.dumps(payload))
    cloned["sourceKind"] = "live_unavailable_fixture_fallback"
    cloned["adapter"] = "LiveInjectiveReadOnlyAdapter -> FixtureInjectiveReadOnlyAdapter"
    cloned["fallbackReason"] = reason
    cloned["sourceDisclosure"] = f"{reason}. Simulated fixture is disclosed; it is not live Injective data."
    if str(cloned.get("marketId") or "").startswith(("demo_fixture:", "simulated_fixture:")):
        market = str(cloned.get("market") or str(cloned.get("marketId")).split(":", 1)[-1] or "INJ-PERP")
        cloned["marketId"] = f"{SIMULATED_FIXTURE_PREFIX}:{market}"
    cloned["sourceCoverage"] = _coverage(
        "partial",
        unavailable=[source_name],
        unknown=["fresh live source fields"],
        explanation=f"{reason}. Fixture fallback is shown, but missing live data remains unknown.",
        sources=[{"name": source_name, "status": "partial"}],
    )
    for item in cloned.get("evidence", []):
        if item.get("id") == evidence_id:
            item["mode"] = "live_read_only"
            item["verification"] = reason
            item["dataQuality"] = "Partial live read; fixture fallback"
            item["adapter"] = "LiveInjectiveReadOnlyAdapter -> FixtureInjectiveReadOnlyAdapter"
            item["sourceKind"] = "live_unavailable_fixture_fallback"
            item["scope"] = item.get("scope") or "read_only_source"
            item["rawRef"] = "live_unavailable:fixture_fallback"
    return cloned


def _coverage(
    status: str,
    *,
    unavailable: list[str] | None = None,
    unknown: list[str] | None = None,
    explanation: str,
    sources: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "unavailableSources": unavailable or [],
        "unknownFields": unknown or [],
        "explanation": explanation,
        "sources": sources or [],
    }


def _clean_url(value: str | None) -> str | None:
    if not value:
        return None
    return value.rstrip("/")


def _format_url(template: str, **values: str) -> str:
    return template.format(**{key: urllib.parse.quote(value) for key, value in values.items()})


def _unwrap_market_payload(data: dict[str, Any], market: str) -> dict[str, Any]:
    if isinstance(data.get("market"), dict):
        return _flatten_market_item(data["market"])
    if isinstance(data.get("data"), dict):
        return _flatten_market_item(data["data"])
    if isinstance(data.get("markets"), list):
        for item in data["markets"]:
            flattened = _flatten_market_item(item) if isinstance(item, dict) else {}
            if _market_matches(market, flattened):
                return flattened
    return _flatten_market_item(data)


def _flatten_market_item(item: dict[str, Any]) -> dict[str, Any]:
    nested = item.get("market") if isinstance(item.get("market"), dict) else {}
    perpetual = item.get("perpetual_info") if isinstance(item.get("perpetual_info"), dict) else {}
    market_info = perpetual.get("market_info") if isinstance(perpetual.get("market_info"), dict) else {}
    funding_info = perpetual.get("funding_info") if isinstance(perpetual.get("funding_info"), dict) else {}
    flattened = {**nested, **item}
    flattened.pop("market", None)
    flattened["market_info"] = market_info
    flattened["funding_info"] = funding_info
    if "market_id" not in flattened and market_info.get("market_id"):
        flattened["market_id"] = market_info["market_id"]
    if "hourly_interest_rate" not in flattened and market_info.get("hourly_interest_rate"):
        flattened["hourly_interest_rate"] = market_info["hourly_interest_rate"]
    if "cumulative_funding" not in flattened and funding_info.get("cumulative_funding"):
        flattened["cumulative_funding"] = funding_info["cumulative_funding"]
    return flattened


def _market_matches(target: str, market_data: dict[str, Any]) -> bool:
    candidates = {
        str(market_data.get("ticker") or ""),
        str(market_data.get("market") or ""),
        str(market_data.get("marketId") or ""),
        str(market_data.get("market_id") or ""),
    }
    if target in candidates:
        return True
    normalized_target = _normalize_market_text(target)
    return any(
        normalized_target == _normalize_market_text(candidate)
        or (normalized_target.startswith("INJ") and _normalize_market_text(candidate).startswith("INJ"))
        for candidate in candidates
        if candidate
    )


def _normalize_market_text(value: str) -> str:
    return "".join(ch for ch in value.upper() if ch.isalnum())


def _looks_like_live_market_id(market_id: str) -> bool:
    if not market_id:
        return False
    lowered = market_id.lower()
    if lowered.startswith(("demo", "fixture", "simulated")):
        return False
    return True


def _first_number(data: dict[str, Any], keys: list[str]) -> float | None:
    for key in keys:
        if key not in data:
            continue
        try:
            return float(data[key])
        except (TypeError, ValueError):
            continue
    return None


def _scaled_market_number(value: float | None, market_data: dict[str, Any]) -> float | None:
    if value is None:
        return None
    decimals = int(_first_number(market_data, ["quote_decimals", "oracle_scale_factor"]) or 0)
    if decimals and abs(value) >= 10 ** decimals:
        return value / (10**decimals)
    return value


def _market_max_leverage(market_data: dict[str, Any]) -> float | None:
    explicit = _first_number(market_data, ["maxLeverage", "max_leverage"])
    if explicit:
        return explicit
    initial_margin_ratio = _first_number(market_data, ["initialMarginRatio", "initial_margin_ratio"])
    if initial_margin_ratio and initial_margin_ratio > 0:
        return round(1 / initial_margin_ratio, 2)
    return None


def _market_funding_rate_pct(market_data: dict[str, Any]) -> float | None:
    explicit = _first_number(market_data, ["fundingRatePct", "funding_rate_pct"])
    if explicit is not None:
        return explicit
    funding_rate = _first_number(market_data, ["fundingRate", "funding_rate", "hourly_interest_rate"])
    if funding_rate is not None:
        return funding_rate * 100
    return None


def _unwrap_positions_payload(data: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(data.get("positions"), list):
        return data["positions"]
    if isinstance(data.get("data"), list):
        return data["data"]
    if isinstance(data.get("position"), dict):
        return [data["position"]]
    if "state" in data:
        state = data.get("state")
        if isinstance(state, dict):
            return [state]
        return []
    return []


def _normalize_position(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "market": str(item.get("market") or item.get("ticker") or item.get("marketId") or "UNKNOWN"),
        "side": "short" if str(item.get("side") or "").lower() == "short" else "long",
        "notionalUsd": _first_number(item, ["notionalUsd", "notional_usd", "notional"]) or 0,
        "leverage": _first_number(item, ["leverage"]) or 1,
        "liquidationPrice": _first_number(item, ["liquidationPrice", "liquidation_price"]) or 0,
        "liquidationDistancePct": _first_number(item, ["liquidationDistancePct", "liquidation_distance_pct"]) or 0,
        "unrealizedPnlUsd": _first_number(item, ["unrealizedPnlUsd", "unrealized_pnl_usd", "unrealizedPnl"]) or 0,
    }
