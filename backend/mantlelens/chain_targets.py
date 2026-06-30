from __future__ import annotations

import os
from dataclasses import asdict, dataclass, replace
from typing import Any


@dataclass(frozen=True)
class ChainTarget:
    id: str
    name: str
    chain_id: int | None
    environment: str
    native_symbol: str
    enabled: bool
    supports_read_only_scan: bool
    supports_assessment_commit: bool
    description: str
    explorer_base_url: str | None = None
    rpc_url: str | None = None
    coming_soon: bool = False
    known_token_allowlist_key: str | None = None

    @property
    def public_label(self) -> str:
        if self.chain_id is None:
            return f"{self.name} · Adapter-ready / Coming soon"
        if self.environment == "testnet":
            return f"{self.name} · Testnet · {self.chain_id}"
        return f"{self.name} · {self.chain_id}"

    def public_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for private_or_internal in (
            "rpc_url",
            "chain_id",
            "native_symbol",
            "supports_read_only_scan",
            "supports_assessment_commit",
            "coming_soon",
            "known_token_allowlist_key",
        ):
            payload.pop(private_or_internal, None)
        payload["chainId"] = self.chain_id
        payload["nativeSymbol"] = self.native_symbol
        payload["enabled"] = self.enabled and self.supports_read_only_scan
        payload["supportsReadOnlyScan"] = self.supports_read_only_scan
        payload["supportsAssessmentCommit"] = self.supports_assessment_commit
        payload["comingSoon"] = self.coming_soon
        payload["knownTokenAllowlistKey"] = self.known_token_allowlist_key
        payload["label"] = self.public_label
        return payload


class ChainTargetError(ValueError):
    pass


def build_chain_targets(config: Any) -> list[ChainTarget]:
    sepolia_rpc = _target_rpc_url(config, target_chain_id=5003, explicit_env="MANTLE_SEPOLIA_RPC_URL")
    mainnet_rpc = _target_rpc_url(config, target_chain_id=5000, explicit_env="MANTLE_MAINNET_RPC_URL")
    sepolia_commit_supported = _commit_supported(config, 5003)
    mainnet_commit_supported = _commit_supported(config, 5000)
    mainnet_enabled = bool(mainnet_rpc)
    return [
        ChainTarget(
            id="mantle-sepolia",
            name="Mantle Sepolia",
            chain_id=5003,
            environment="testnet",
            native_symbol="MNT",
            enabled=bool(sepolia_rpc),
            supports_read_only_scan=bool(sepolia_rpc),
            supports_assessment_commit=sepolia_commit_supported,
            description="Recommended for demo and live smoke testing.",
            explorer_base_url=_target_explorer_url(config, 5003),
            rpc_url=sepolia_rpc,
            known_token_allowlist_key="mantle-sepolia",
        ),
        ChainTarget(
            id="mantle-mainnet",
            name="Mantle Mainnet",
            chain_id=5000,
            environment="mainnet",
            native_symbol="MNT",
            enabled=mainnet_enabled,
            supports_read_only_scan=mainnet_enabled,
            supports_assessment_commit=mainnet_commit_supported,
            description=(
                "Production Mantle target. Enable by configuring a Mantle Mainnet read-only RPC."
                if not mainnet_enabled
                else "Production Mantle target for read-only wallet scans."
            ),
            explorer_base_url=_target_explorer_url(config, 5000),
            rpc_url=mainnet_rpc,
            coming_soon=not mainnet_enabled,
            known_token_allowlist_key="mantle-mainnet",
        ),
        ChainTarget(
            id="custom-evm",
            name="Custom EVM network",
            chain_id=None,
            environment="custom",
            native_symbol="ETH",
            enabled=False,
            supports_read_only_scan=False,
            supports_assessment_commit=False,
            description="Adapter-ready extension point. Custom EVM targets are not enabled in this demo build.",
            coming_soon=True,
            known_token_allowlist_key="custom-evm",
        ),
    ]


def public_chain_targets(config: Any) -> list[dict[str, Any]]:
    return [target.public_dict() for target in build_chain_targets(config)]


def default_chain_target_id(config: Any) -> str:
    explicit = os.getenv("MANTLELENS_DEFAULT_TARGET_ID", "").strip()
    if explicit:
        return explicit
    if int(getattr(config, "chain_id", 0) or 0) == 5000 and _target_rpc_url(config, target_chain_id=5000, explicit_env="MANTLE_MAINNET_RPC_URL"):
        return "mantle-mainnet"
    return "mantle-sepolia"


def resolve_chain_target(config: Any, *, target_id: str | None, chain_id: int | None) -> ChainTarget:
    targets = {target.id: target for target in build_chain_targets(config)}
    if target_id:
        target = targets.get(str(target_id))
        if not target:
            raise ChainTargetError(f"Unknown scan target: {target_id}")
    else:
        target = targets.get(default_chain_target_id(config)) or targets["mantle-sepolia"]
    if chain_id is not None and target.chain_id is not None and int(chain_id) != int(target.chain_id):
        raise ChainTargetError("scan target chainId mismatch")
    if not target.enabled or not target.supports_read_only_scan:
        raise ChainTargetError(f"{target.name} read-only adapter is not enabled yet")
    return target


def config_for_chain_target(config: Any, target: ChainTarget) -> Any:
    if target.chain_id is None:
        raise ChainTargetError("Custom EVM target is adapter-ready but not enabled")
    return replace(
        config,
        chain_id=target.chain_id,
        mantle_rpc_url=target.rpc_url,
        moralis_node_url=None,
        mantle_explorer_base_url=(target.explorer_base_url or getattr(config, "mantle_explorer_base_url", "")).rstrip("/"),
    )


def _target_rpc_url(config: Any, *, target_chain_id: int, explicit_env: str) -> str | None:
    explicit = _optional_env(explicit_env)
    if explicit:
        return explicit
    if int(getattr(config, "chain_id", 0) or 0) == target_chain_id:
        return getattr(config, "effective_rpc_url", None)
    return None


def _target_explorer_url(config: Any, chain_id: int) -> str:
    if int(getattr(config, "chain_id", 0) or 0) == chain_id:
        return str(getattr(config, "mantle_explorer_base_url", "") or _default_explorer_url(chain_id)).rstrip("/")
    return _default_explorer_url(chain_id)


def _default_explorer_url(chain_id: int) -> str:
    if chain_id == 5003:
        return "https://sepolia.mantlescan.xyz"
    return "https://mantlescan.xyz"


def _commit_supported(config: Any, chain_id: int) -> bool:
    return (
        int(getattr(config, "chain_id", 0) or 0) == chain_id
        and bool(getattr(config, "assessment_contract_address", None))
        and bool(getattr(config, "wallet_private_key", None))
    )


def _optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None
