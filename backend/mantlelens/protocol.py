from __future__ import annotations

from typing import Any

from .adapters import FixtureWalletAdapter
from .config import MantleLensConfig
from .workflows import WalletGuardRunner


AGENT_ID = "mantlelens-wallet-guard-demo"
AGENT_NAME = "MantleLens Wallet Guard"
AGENT_VERSION = "0.10.0"


def agent_registration(base_url: str = "http://127.0.0.1:8765") -> dict[str, Any]:
    config = MantleLensConfig.from_env()
    return {
        "schemaVersion": "mantlelens.agent_registration.v1",
        "agentId": AGENT_ID,
        "name": AGENT_NAME,
        "version": AGENT_VERSION,
        "description": "Evidence-grounded, simulation-only wallet risk agent for Mantle.",
        "agentURI": f"{base_url}/.well-known/agent-card.json",
        "serviceURI": base_url,
        "chainId": config.chain_id,
        "networkName": config.network_name,
        "capabilities": [
            "wallet_risk_scan",
            "approval_risk_detection",
            "suspicious_transfer_detection",
            "portfolio_exposure_scoring",
            "rwa_yield_risk_scoring",
            "evidence_bundle",
            "simulation_only_actions",
            "benchmark_history",
        ],
        "safety": {
            "defaultMode": "view_only_simulation_only",
            "realExecutionAllowed": False,
            "mcpMode": "read_only",
            "claimsRequireEvidence": True,
        },
        "endpoints": {
            "agentCard": f"{base_url}/.well-known/agent-card.json",
            "mcp": f"{base_url}/mcp",
            "scan": f"{base_url}/api/wallet/scan",
            "benchmark": f"{base_url}/api/benchmark",
        },
    }


def agent_card(base_url: str = "http://127.0.0.1:8765") -> dict[str, Any]:
    config = MantleLensConfig.from_env()
    return {
        "schemaVersion": "a2a.agent_card.v1",
        "id": AGENT_ID,
        "name": AGENT_NAME,
        "version": AGENT_VERSION,
        "description": "Scans Mantle wallet approvals, suspicious transfers, portfolio concentration, DeFi stub, and RWA/yield exposure with evidence-bound explanations.",
        "url": base_url,
        "provider": {
            "name": "MantleLens",
            "url": base_url,
        },
        "chain": {
            "chainId": config.chain_id,
            "networkName": config.network_name,
        },
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": [
            {
                "id": "scan_wallet_risk",
                "name": "Scan Wallet Risk",
                "description": "Return wallet risk score, top risks, evidence bundle, and trace for a Mantle demo fixture.",
            },
            {
                "id": "detect_approval_risk",
                "name": "Detect Approval Risk",
                "description": "Return active approval risk items confirmed by allowance.",
            },
            {
                "id": "detect_suspicious_transfers",
                "name": "Detect Suspicious Transfers",
                "description": "Return suspicious recent transfer candidates from bounded known-token logs.",
            },
            {
                "id": "score_portfolio_exposure",
                "name": "Score Portfolio Exposure",
                "description": "Return known-token portfolio concentration and Mantle yield exposure.",
            },
            {
                "id": "score_rwa_yield_risk",
                "name": "Score RWA/Yield Risk",
                "description": "Return USDY/mUSD/mETH/cmETH risk context where available.",
            },
            {
                "id": "build_evidence_bundle",
                "name": "Build Evidence Bundle",
                "description": "Return evidence items and evidence bundle hash for an assessment.",
            },
            {
                "id": "get_benchmark_history",
                "name": "Get Benchmark History",
                "description": "Return local benchmark records for a wallet hash.",
            },
        ],
        "security": {
            "viewOnly": True,
            "simulationOnly": True,
            "realExecutionAllowed": False,
        },
    }


def mcp_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "scan_wallet_risk",
            "description": "Return a Mantle wallet risk assessment from a demo fixture.",
            "inputSchema": _fixture_schema(),
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "get_wallet_exposure",
            "description": "Return known-token balances and exposure source availability.",
            "inputSchema": _fixture_schema(),
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "get_approval_risks",
            "description": "Return active approval risk rows.",
            "inputSchema": _fixture_schema(),
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "get_suspicious_transfers",
            "description": "Return suspicious transfer candidates.",
            "inputSchema": _fixture_schema(),
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "get_rwa_yield_risks",
            "description": "Return RWA/yield exposure payload and related limitations.",
            "inputSchema": _fixture_schema(),
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "get_evidence_bundle",
            "description": "Return evidence bundle for a wallet risk assessment.",
            "inputSchema": _fixture_schema(),
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "get_benchmark_history",
            "description": "Return local benchmark records. Optional walletHash argument.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "walletHash": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
            },
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "record_wallet_assessment",
            "description": "P0 MCP read-only projection. Returns instructions for REST commit; does not mutate state.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "assessmentHash": {"type": "string"},
                    "dryRun": {"type": "boolean", "const": True},
                },
                "required": ["assessmentHash", "dryRun"],
            },
            "annotations": {"readOnlyHint": True},
        },
    ]


def mcp_list_response(request_id: Any = None) -> dict[str, Any]:
    return _json_rpc_result(request_id, {"tools": mcp_tools()})


def mcp_call_response(
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    request_id: Any = None,
) -> dict[str, Any]:
    arguments = arguments or {}
    result = call_mcp_tool(name, arguments)
    return _json_rpc_result(
        request_id,
        {
            "content": [
                {
                    "type": "json",
                    "json": result,
                }
            ],
            "isError": False,
        },
    )


def call_mcp_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    fixture_id = arguments.get("fixtureId", "high_risk_wallet")
    adapter = FixtureWalletAdapter()

    if name == "scan_wallet_risk":
        package = WalletGuardRunner(adapter=adapter).scan_wallet(fixture_id=fixture_id)
        return {
            "assessment": package["assessment"],
            "coverage": package["coverage"],
            "trace": package["trace"],
        }

    if name == "get_wallet_exposure":
        fixture = adapter.load_fixture(fixture_id)
        raw = adapter.scan_raw(fixture_id)
        return {
            "wallet": fixture["wallet"],
            "balances": raw["toolOutputs"]["getKnownTokenBalances"]["output"]["balances"],
            "nativeBalance": raw["toolOutputs"]["getNativeBalance"]["output"]["balance"],
            "sourceAvailability": raw["sourceAvailability"],
            "dataCoverage": raw["toolOutputs"]["getKnownTokenBalances"]["dataCoverage"],
        }

    if name == "get_approval_risks":
        raw = adapter.scan_raw(fixture_id)
        return raw["toolOutputs"]["getTokenApprovals"]["output"]

    if name == "get_suspicious_transfers":
        raw = adapter.scan_raw(fixture_id)
        return raw["toolOutputs"]["getTransferLogs"]["output"]

    if name == "get_rwa_yield_risks":
        raw = adapter.scan_raw(fixture_id)
        return raw["toolOutputs"]["getRwaYieldExposure"]["output"]

    if name == "get_evidence_bundle":
        package = WalletGuardRunner(adapter=adapter).scan_wallet(fixture_id=fixture_id, include_explanation=False)
        return package["evidenceBundle"]

    if name == "get_benchmark_history":
        from .ledger import LEDGER

        return {
            "records": LEDGER.history(
                wallet_hash=arguments.get("walletHash"),
                limit=int(arguments.get("limit", 20)),
            )
        }

    if name == "record_wallet_assessment":
        return {
            "status": "not_mutated",
            "message": "MCP P0 is read-only. Use /api/assessment/commit with user confirmation and idempotencyKey.",
            "assessmentHash": arguments.get("assessmentHash"),
            "realExecutionAllowed": False,
        }

    raise ValueError(f"Unknown MCP tool: {name}")


def _fixture_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "fixtureId": {
                "type": "string",
                "enum": ["low_risk_wallet", "moderate_partial_wallet", "high_risk_wallet"],
                "default": "high_risk_wallet",
            }
        },
    }


def _json_rpc_result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result,
    }
