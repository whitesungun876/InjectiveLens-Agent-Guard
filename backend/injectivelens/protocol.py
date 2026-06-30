from __future__ import annotations

from typing import Any

from .adapters import select_injective_adapter
from .fixtures import (
    DEFAULT_ACCOUNT,
    DEFAULT_NETWORK,
    DEFAULT_SUBACCOUNT_ID,
    build_agent_audit,
    build_preflight_assessment,
    safer_trade_simulation,
)


AGENT_ID = "injectivelens-agent-guard-demo"
AGENT_NAME = "InjectiveLens Agent Guard"
AGENT_VERSION = "0.9.0"
INJECTIVE_TESTNET_CHAIN_ID = "injective-888"


def agent_registration(base_url: str = "http://127.0.0.1:8765") -> dict[str, Any]:
    return {
        "schemaVersion": "injectivelens.agent_registration.v1",
        "agentId": AGENT_ID,
        "name": AGENT_NAME,
        "version": AGENT_VERSION,
        "description": "A safety and proof layer before AI agents execute trades on Injective.",
        "agentURI": f"{base_url}/.well-known/agent-card.json",
        "serviceURI": base_url,
        "network": DEFAULT_NETWORK,
        "chainId": INJECTIVE_TESTNET_CHAIN_ID,
        "capabilities": [
            "natural_language_trade_intent_parsing",
            "injective_account_state_read",
            "injective_market_snapshot_read",
            "injective_position_context_read",
            "pre_trade_risk_decision",
            "allowed_blocked_action_policy",
            "simulation_only_safer_trade",
            "assessment_hash_record_and_verify",
            "mcp_tool_surface",
        ],
        "safety": {
            "defaultMode": "read_only_simulation_only",
            "realExecutionAllowed": False,
            "mcpMode": "read_only_preflight",
            "claimsRequireEvidence": True,
            "noPrivateKeyOrSeedPhrase": True,
            "noOrderPlacement": True,
        },
        "endpoints": {
            "agentCard": f"{base_url}/.well-known/agent-card.json",
            "mcp": f"{base_url}/mcp",
            "preflight": f"{base_url}/api/injective/preflight",
            "latestAssessment": f"{base_url}/api/injective/preflight/latest",
            "history": f"{base_url}/api/history/preflight",
            "audit": f"{base_url}/api/agent/audit",
        },
    }


def agent_card(base_url: str = "http://127.0.0.1:8765") -> dict[str, Any]:
    return {
        "schemaVersion": "a2a.agent_card.v1",
        "id": AGENT_ID,
        "name": AGENT_NAME,
        "version": AGENT_VERSION,
        "description": "Blocks high-risk AI trading actions before execution, binds the decision to evidence, simulates a safer trade, and verifies an assessment proof.",
        "url": base_url,
        "provider": {
            "name": "InjectiveLens",
            "url": base_url,
        },
        "chain": {
            "chainId": INJECTIVE_TESTNET_CHAIN_ID,
            "networkName": "Injective testnet",
        },
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": [
            {
                "id": "preflight_trade_action",
                "name": "Pre-flight Trade Action",
                "description": "Parse a natural-language trade request and return an allow/warn/block decision with evidence.",
            },
            {
                "id": "get_injective_account_state",
                "name": "Get Injective Account State",
                "description": "Read account and subaccount context through the configured read-only adapter.",
            },
            {
                "id": "get_market_snapshot",
                "name": "Get Market Snapshot",
                "description": "Read Injective market context used by the risk decision.",
            },
            {
                "id": "get_open_positions",
                "name": "Get Open Positions",
                "description": "Read open position context for the requested subaccount.",
            },
            {
                "id": "simulate_safer_trade",
                "name": "Simulate Safer Trade",
                "description": "Return a lower-risk trade proposal without placing an order.",
            },
            {
                "id": "get_latest_assessment",
                "name": "Get Latest Assessment",
                "description": "Return the latest persisted assessment and proof status when available.",
            },
            {
                "id": "record_assessment_projection",
                "name": "Record Assessment Projection",
                "description": "Read-only MCP projection of the proof-recording boundary; it does not mutate chain or local state.",
            },
        ],
        "security": {
            "viewOnly": True,
            "simulationOnly": True,
            "realExecutionAllowed": False,
            "privateKeyRequired": False,
            "seedPhraseRequired": False,
        },
    }


def mcp_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "preflight_trade_action",
            "description": "Parse a trade request and return an InjectiveLens pre-flight assessment.",
            "inputSchema": _preflight_schema(),
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "get_injective_account_state",
            "description": "Return account and subaccount context from the selected read-only Injective adapter.",
            "inputSchema": _account_schema(),
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "get_market_snapshot",
            "description": "Return market evidence from the selected read-only Injective adapter.",
            "inputSchema": _market_schema(),
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "get_open_positions",
            "description": "Return open position context from the selected read-only Injective adapter.",
            "inputSchema": _positions_schema(),
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "simulate_safer_trade",
            "description": "Return a safer-trade simulation. No order is placed.",
            "inputSchema": _preflight_schema(required_prompt=False),
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "get_latest_assessment",
            "description": "Return latest persisted assessment and proof status when available.",
            "inputSchema": {"type": "object", "properties": {}},
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "record_assessment_projection",
            "description": "Return proof-recording instructions. MCP P0 stays read-only and does not mutate state.",
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
    latest_assessment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        result = call_mcp_tool(name, arguments or {}, latest_assessment=latest_assessment)
        return _json_rpc_result(
            request_id,
            {
                "content": [{"type": "json", "json": result}],
                "isError": False,
            },
        )
    except ValueError as exc:
        return _json_rpc_result(
            request_id,
            {
                "content": [{"type": "text", "text": str(exc)}],
                "isError": True,
            },
        )


def mcp_error_response(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
        },
    }


def call_mcp_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    latest_assessment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if name == "preflight_trade_action":
        assessment = build_preflight_assessment(_request_from_arguments(arguments))
        return {
            "assessment": _assessment_projection(assessment),
            "decision": assessment["decision"],
            "evidence": assessment["evidence"],
            "sourceCoverage": assessment["sourceCoverage"],
            "simulation": assessment["simulation"],
            "audit": build_agent_audit(assessment),
            "execution": _execution_boundary(),
        }

    if name == "get_injective_account_state":
        request = _request_from_arguments(arguments, require_prompt=False)
        adapter = select_injective_adapter(request["mode"])
        return adapter.account_state(
            request["address"],
            request["subaccountId"],
            request["network"],
            request["mode"],
        )

    if name == "get_market_snapshot":
        request = _request_from_arguments(arguments, require_prompt=False)
        adapter = select_injective_adapter(request["mode"])
        return adapter.market_snapshot(
            str(arguments.get("market") or "INJ-PERP"),
            request["network"],
            request["mode"],
        )

    if name == "get_open_positions":
        request = _request_from_arguments(arguments, require_prompt=False)
        adapter = select_injective_adapter(request["mode"])
        return adapter.positions(request["subaccountId"], request["network"], request["mode"])

    if name == "simulate_safer_trade":
        assessment = build_preflight_assessment(_request_from_arguments(arguments, require_prompt=False))
        return {
            "simulation": safer_trade_simulation(
                assessment["parseResult"]["tradeIntent"],
                assessment["decision"]["riskScore"],
            ),
            "execution": _execution_boundary(),
        }

    if name == "get_latest_assessment":
        if not latest_assessment:
            return {
                "status": "not_found",
                "message": "No persisted pre-flight assessment is available.",
            }
        return {
            "status": "available",
            "assessment": _assessment_projection(latest_assessment),
            "proof": latest_assessment.get("proof", {}),
        }

    if name == "record_assessment_projection":
        return {
            "status": "not_mutated",
            "message": "MCP P0 is read-only. Use /api/proof/record with explicit user confirmation to record an assessment hash.",
            "assessmentHash": arguments.get("assessmentHash"),
            "realExecutionAllowed": False,
            "requiredConfirmation": "user_confirmed_record_assessment",
        }

    raise ValueError(f"Unknown MCP tool: {name}")


def _request_from_arguments(arguments: dict[str, Any], require_prompt: bool = True) -> dict[str, str]:
    prompt = str(arguments.get("prompt") or "Open a 10x long INJ-PERP using 60% of available margin.").strip()
    if require_prompt and not prompt:
        raise ValueError("prompt is required")
    mode = str(arguments.get("mode") or "demo_scenario")
    if mode not in {"demo_scenario", "live_read_only"}:
        raise ValueError("mode must be demo_scenario or live_read_only")
    return {
        "prompt": prompt,
        "address": str(arguments.get("address") or DEFAULT_ACCOUNT),
        "subaccountId": str(arguments.get("subaccountId") or DEFAULT_SUBACCOUNT_ID),
        "network": str(arguments.get("network") or DEFAULT_NETWORK),
        "mode": mode,
    }


def _assessment_projection(assessment: dict[str, Any]) -> dict[str, Any]:
    return {
        "assessmentId": assessment["assessmentId"],
        "assessmentHash": assessment["assessmentHash"],
        "createdAt": assessment["createdAt"],
        "network": assessment["request"]["network"],
        "mode": assessment["request"]["mode"],
        "prompt": assessment["request"]["prompt"],
        "tradeIntent": assessment["parseResult"]["tradeIntent"],
        "decision": assessment["decision"]["decision"],
        "riskScore": assessment["decision"]["riskScore"],
        "riskLevel": assessment["decision"]["riskLevel"],
        "topRisks": assessment["decision"]["topRisks"],
        "proofStatus": assessment["proof"]["status"],
    }


def _execution_boundary() -> dict[str, Any]:
    return {
        "realExecutionAllowed": False,
        "orderPlaced": False,
        "autoSigningAllowed": False,
        "privateKeyRequired": False,
        "seedPhraseRequired": False,
        "mode": "read_only_simulation_only",
    }


def _preflight_schema(required_prompt: bool = True) -> dict[str, Any]:
    schema = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "default": "Open a 10x long INJ-PERP using 60% of available margin.",
            },
            "address": {"type": "string", "default": DEFAULT_ACCOUNT},
            "subaccountId": {"type": "string", "default": DEFAULT_SUBACCOUNT_ID},
            "network": {"type": "string", "enum": [DEFAULT_NETWORK], "default": DEFAULT_NETWORK},
            "mode": {"type": "string", "enum": ["demo_scenario", "live_read_only"], "default": "demo_scenario"},
        },
    }
    if required_prompt:
        schema["required"] = ["prompt"]
    return schema


def _account_schema() -> dict[str, Any]:
    schema = _preflight_schema(required_prompt=False)
    schema["properties"].pop("prompt")
    return schema


def _market_schema() -> dict[str, Any]:
    schema = _account_schema()
    schema["properties"]["market"] = {"type": "string", "default": "INJ-PERP"}
    return schema


def _positions_schema() -> dict[str, Any]:
    return _account_schema()


def _json_rpc_result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result,
    }
