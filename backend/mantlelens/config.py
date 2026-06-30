from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class KnownToken:
    symbol: str
    token_address: str
    decimals: int
    price_usd: float | None = None


@dataclass(frozen=True)
class MantleLensConfig:
    chain_id: int = 5000
    mantle_rpc_url: str | None = "https://rpc.mantle.xyz"
    moralis_node_url: str | None = None
    goplus_base_url: str = "https://api.gopluslabs.io"
    goplus_api_key: str | None = None
    moralis_base_url: str = "https://deep-index.moralis.io/api/v2.2"
    moralis_api_key: str | None = None
    moralis_chain: str = "mantle"
    moralis_data_api_enabled: bool = False
    moralis_balances_enabled: bool = False
    moralis_history_enabled: bool = False
    etherscan_v2_base_url: str = "https://api.etherscan.io/v2/api"
    etherscan_v2_api_key: str | None = None
    assessment_contract_address: str | None = None
    wallet_private_key: str | None = None
    mantle_explorer_base_url: str = "https://mantlescan.xyz"
    live_request_timeout_sec: float = 3.0
    live_request_retries: int = 1
    live_scan_deadline_sec: float = 15.0
    tx_simulation_rpc_url: str | None = None
    tx_simulation_rpc_method: str = "tenderly_simulateTransaction"
    tx_simulation_provider: str = "tenderly_rpc"
    tx_simulation_timeout_sec: float = 5.0
    known_tokens: tuple[KnownToken, ...] = ()

    @classmethod
    def from_env(cls) -> "MantleLensConfig":
        return cls(
            chain_id=int(os.getenv("MANTLE_CHAIN_ID") or os.getenv("CHAIN_ID") or "5000"),
            mantle_rpc_url=_optional_env("MANTLE_RPC_URL", "https://rpc.mantle.xyz"),
            moralis_node_url=_optional_env("MORALIS_NODE_URL"),
            goplus_base_url=os.getenv("GOPLUS_BASE_URL", "https://api.gopluslabs.io").rstrip("/"),
            goplus_api_key=_optional_env("GOPLUS_API_KEY"),
            moralis_base_url=os.getenv("MORALIS_BASE_URL", "https://deep-index.moralis.io/api/v2.2").rstrip("/"),
            moralis_api_key=_optional_env("MORALIS_API_KEY"),
            moralis_chain=os.getenv("MORALIS_CHAIN", "mantle"),
            moralis_data_api_enabled=_bool_env("MORALIS_DATA_API_ENABLED", default=False),
            moralis_balances_enabled=_bool_env("MORALIS_BALANCES_ENABLED", default=False),
            moralis_history_enabled=_bool_env("MORALIS_HISTORY_ENABLED", default=False),
            etherscan_v2_base_url=os.getenv("ETHERSCAN_V2_BASE_URL", "https://api.etherscan.io/v2/api"),
            etherscan_v2_api_key=_optional_env("ETHERSCAN_V2_API_KEY")
            or _optional_env("MANTLESCAN_API_KEY"),
            assessment_contract_address=_optional_env("ASSESSMENT_CONTRACT_ADDRESS")
            or _optional_env("ASSESSMENT_LOGGER_ADDRESS"),
            wallet_private_key=_optional_env("PRIVATE_KEY") or _optional_env("WALLET_PRIVATE_KEY"),
            mantle_explorer_base_url=os.getenv("MANTLE_EXPLORER_BASE_URL", "https://mantlescan.xyz").rstrip("/"),
            live_request_timeout_sec=_float_env("LIVE_REQUEST_TIMEOUT_SEC", default=3.0, minimum=0.5, maximum=8.0),
            live_request_retries=_int_env("LIVE_REQUEST_RETRIES", default=1, minimum=0, maximum=3),
            live_scan_deadline_sec=_float_env("LIVE_SCAN_DEADLINE_SEC", default=15.0, minimum=3.0, maximum=30.0),
            tx_simulation_rpc_url=_optional_env("TX_SIMULATION_RPC_URL") or _optional_env("TENDERLY_SIMULATION_RPC_URL"),
            tx_simulation_rpc_method=os.getenv("TX_SIMULATION_RPC_METHOD", "tenderly_simulateTransaction"),
            tx_simulation_provider=os.getenv("TX_SIMULATION_PROVIDER", "tenderly_rpc"),
            tx_simulation_timeout_sec=_float_env("TX_SIMULATION_TIMEOUT_SEC", default=5.0, minimum=1.0, maximum=15.0),
            known_tokens=_known_tokens_from_env(),
        )

    @property
    def effective_rpc_url(self) -> str | None:
        return self.moralis_node_url or self.mantle_rpc_url

    @property
    def network_name(self) -> str:
        return _network_name(self.chain_id)

    @property
    def moralis_data_available(self) -> bool:
        return self.moralis_balances_available or self.moralis_history_available

    @property
    def moralis_balances_available(self) -> bool:
        return bool(self.moralis_api_key and (self.moralis_data_api_enabled or self.moralis_balances_enabled))

    @property
    def moralis_history_available(self) -> bool:
        return bool(self.moralis_api_key and (self.moralis_data_api_enabled or self.moralis_history_enabled))

    def source_snapshot(self) -> dict[str, dict[str, Any]]:
        return {
            "mantleRpc": {
                "status": "available" if self.effective_rpc_url else "unavailable",
                "limitation": "Public RPC can read native balance and configured ERC20 calls; arbitrary wallet inventory needs an indexer.",
            },
            "moralisRpc": {
                "status": "available" if self.moralis_node_url else "unavailable",
                "limitation": "Use MORALIS_NODE_URL from the Moralis dashboard to route Mantle JSON-RPC through Moralis RPC Nodes.",
            },
            "goPlus": {
                "status": "available",
                "limitation": "Token and address security signals are advisory, not proof of safety.",
            },
            "moralis": {
                "status": "available" if self.moralis_data_available else "unavailable",
                "limitation": "Moralis balances/history are behind MORALIS_BALANCES_ENABLED and MORALIS_HISTORY_ENABLED switches; disabled sources are unknown, not safe.",
            },
            "etherscanV2": {
                "status": "available" if self.etherscan_v2_api_key else "unavailable",
                "limitation": "Used for explorer-indexed transactions/logs when ETHERSCAN_V2_API_KEY or MANTLESCAN_API_KEY is configured.",
            },
            "assessmentLogger": {
                "status": "available" if self.assessment_contract_address and self.wallet_private_key else "unavailable",
                "limitation": "Writes only assessment records; missing contract/private key returns pending_unavailable and never fabricates a tx hash.",
            },
            "txSimulation": {
                "status": "available" if self.tx_simulation_rpc_url else "unavailable",
                "limitation": "Uses configured simulation RPC only; MantleLens never broadcasts simulated transactions.",
            },
        }

    def public_provider_status(self) -> dict[str, Any]:
        from .chain_targets import default_chain_target_id, public_chain_targets

        sources = self.source_snapshot()
        return {
            "schemaVersion": "mantlelens.provider_status.v1",
            "chain": {
                "chainId": self.chain_id,
                "networkName": self.network_name,
                "displayName": f"{self.network_name} · {self.chain_id}",
            },
            "defaultTargetId": default_chain_target_id(self),
            "chainTargets": public_chain_targets(self),
            "rpc": {
                "configured": bool(self.effective_rpc_url),
                "provider": "moralis" if self.moralis_node_url else "mantle_rpc",
            },
            "assessmentLogger": {
                "status": "configured" if self.assessment_contract_address and self.wallet_private_key else "unavailable",
                "contractAddress": self.assessment_contract_address,
                "explorerBaseUrl": self.mantle_explorer_base_url,
                "privateKeyConfigured": bool(self.wallet_private_key),
                "mode": "real_onchain_manual" if self.assessment_contract_address and self.wallet_private_key else "unavailable",
            },
            "sources": {
                name: {"status": source.get("status"), "limitation": source.get("limitation")}
                for name, source in sources.items()
            },
            "secrets": {
                "privateKeysExposed": False,
                "rawRpcUrlExposed": False,
                "rawApiKeysExposed": False,
            },
        }


def _optional_env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value or None


def _bool_env(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, *, default: int, minimum: int, maximum: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    parsed = int(value)
    return max(minimum, min(maximum, parsed))


def _float_env(name: str, *, default: float, minimum: float, maximum: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    parsed = float(value)
    return max(minimum, min(maximum, parsed))


def _known_tokens_from_env() -> tuple[KnownToken, ...]:
    raw = os.getenv("MANTLE_KNOWN_TOKENS_JSON")
    if not raw:
        return ()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("MANTLE_KNOWN_TOKENS_JSON must be valid JSON") from exc
    if not isinstance(parsed, list):
        raise ValueError("MANTLE_KNOWN_TOKENS_JSON must be a JSON array")
    tokens: list[KnownToken] = []
    for item in parsed:
        if not isinstance(item, dict):
            raise ValueError("Each known token entry must be an object")
        tokens.append(
            KnownToken(
                symbol=str(item["symbol"]),
                token_address=str(item["tokenAddress"]),
                decimals=int(item["decimals"]),
                price_usd=float(item["priceUsd"]) if item.get("priceUsd") is not None else None,
            )
        )
    return tuple(tokens)


def _network_name(chain_id: int) -> str:
    if chain_id == 5003:
        return "Mantle Sepolia"
    if chain_id == 5000:
        return "Mantle Mainnet"
    return f"Mantle Chain {chain_id}"
