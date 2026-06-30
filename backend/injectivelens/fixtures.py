from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from .parser import parse_trade_intent
from .proof import initial_proof_record


DEFAULT_ACCOUNT = os.getenv("INJECTIVE_DEMO_ACCOUNT") or "inj1wrse2035wdnxrq4gwhnxp0nmeyg6u3vss5uvlp"
DEFAULT_SUBACCOUNT_ID = "0x0000000000000000000000000000000000000000000000000000000000000000"
DEFAULT_NETWORK = "injective_testnet"
FIXED_TIMESTAMP = "2026-06-26T10:00:00Z"
SIMULATED_FIXTURE_PREFIX = "simulated_fixture"


def build_preflight_assessment(request: dict[str, Any], adapter: Any | None = None) -> dict[str, Any]:
    prompt = str(request.get("prompt") or "Open a 10x long INJ-PERP using 60% of available margin.")
    address = str(request.get("address") or DEFAULT_ACCOUNT)
    subaccount_id = str(request.get("subaccountId") or DEFAULT_SUBACCOUNT_ID)
    network = str(request.get("network") or DEFAULT_NETWORK)
    mode = str(request.get("mode") or "demo_scenario")

    if adapter is None:
        from .adapters import select_injective_adapter

        adapter = select_injective_adapter(mode)

    parse_result = parse_trade_intent(prompt)
    intent = {
        **parse_result["tradeIntent"],
        "coverageRequestedPartial": any("partial coverage" in warning.lower() for warning in parse_result.get("warnings", [])),
    }
    parse_result = {**parse_result, "tradeIntent": intent}
    account_state = adapter.account_state(address, subaccount_id, network, mode)
    market_snapshot = adapter.market_snapshot(intent["market"], network, mode)
    positions_payload = adapter.positions(subaccount_id, network, mode)
    positions = positions_payload["positions"]
    source_coverage = combine_source_coverage(mode, intent, account_state, market_snapshot, positions_payload)
    decision = evaluate_trade_risk(intent, account_state, market_snapshot, positions, mode, source_coverage)
    evidence = _evidence_items(intent, mode, account_state, market_snapshot, positions_payload)
    simulation = safer_trade_simulation(intent, decision["riskScore"])

    assessment_seed = {
        "request": {
            "prompt": prompt,
            "address": address,
            "subaccountId": subaccount_id,
            "network": network,
            "mode": mode,
        },
        "parseResult": parse_result,
        "decision": decision,
        "evidenceIds": [item["id"] for item in evidence],
        "sourceCoverage": source_coverage,
    }
    assessment_hash = _hash_object(assessment_seed)
    assessment_id = f"preflight_{assessment_hash[2:14]}"
    proof = initial_proof_record(mode, decision, network, assessment_hash)

    return {
        "assessmentId": assessment_id,
        "assessmentHash": assessment_hash,
        "request": assessment_seed["request"],
        "parseResult": parse_result,
        "decision": decision,
        "evidence": evidence,
        "sourceCoverage": source_coverage,
        "simulation": simulation,
        "proof": proof,
        "createdAt": FIXED_TIMESTAMP,
        "accountState": account_state,
        "marketSnapshot": market_snapshot,
        "positions": positions,
    }


def account_state_fixture(address: str, subaccount_id: str, network: str, mode: str) -> dict[str, Any]:
    return {
        "network": network,
        "address": address,
        "subaccountId": subaccount_id,
        "subaccountKind": subaccount_kind(subaccount_id),
        "sourceKind": "demo_replay_fixture" if mode == "demo_scenario" else "simulated_fixture",
        "adapter": "FixtureInjectiveReadOnlyAdapter",
        "sourceDisclosure": "Replay account fixture; not a live Injective subaccount read.",
        "balances": [
            {"denom": "INJ", "amount": "125.0", "usdValue": 3125.0, "source": "demo fixture"},
            {"denom": "USDT", "amount": "9200.0", "usdValue": 9200.0, "source": "demo fixture"},
        ],
        "availableMarginUsd": 12500.0,
        "sourceCoverage": source_coverage_fixture(mode, {"market": "INJ-PERP"}),
        "evidence": [_evidence_items({"market": "INJ-PERP", "leverage": 1, "side": "long", "marginUsagePct": 10}, mode)[1]],
    }


def market_snapshot_fixture(market: str, network: str, mode: str) -> dict[str, Any]:
    mark_price = 24.8 if market == "INJ-PERP" else 61500.0
    return {
        "network": network,
        "market": market,
        "marketId": f"{SIMULATED_FIXTURE_PREFIX}:{market}",
        "sourceKind": "demo_replay_fixture" if mode == "demo_scenario" else "simulated_market_fixture",
        "adapter": "FixtureInjectiveReadOnlyAdapter",
        "sourceDisclosure": "Simulated market fixture; not a live Injective market id.",
        "markPrice": mark_price,
        "oraclePrice": mark_price * 0.998,
        "spreadBps": 18,
        "fundingRatePct": 0.012,
        "maxLeverage": 20,
        "sourceCoverage": source_coverage_fixture(mode, {"market": market}),
        "evidence": [_evidence_items({"market": market, "leverage": 1, "side": "long", "marginUsagePct": 10}, mode)[2]],
    }


def positions_fixture(subaccount_id: str, network: str, mode: str) -> dict[str, Any]:
    timestamp = FIXED_TIMESTAMP
    return {
        "network": network,
        "subaccountId": subaccount_id,
        "subaccountKind": subaccount_kind(subaccount_id),
        "sourceKind": "simulation_model",
        "adapter": "FixtureInjectiveReadOnlyAdapter",
        "sourceDisclosure": "Position projection used for pre-execution simulation; no order was placed.",
        "positions": [
            {
                "market": "INJ-PERP",
                "side": "long",
                "notionalUsd": 3200,
                "leverage": 3,
                "liquidationPrice": 18.4,
                "liquidationDistancePct": 25.8,
                "unrealizedPnlUsd": 42.7,
            }
        ],
        "sourceCoverage": source_coverage_fixture(mode, {"market": "INJ-PERP"}),
        "evidence": [
            {
                "id": "ev_position_001",
                "source": "Injective position model",
                "claim": "Simulated liquidation distance is below the configured safety threshold.",
                "mode": "simulated",
                "verification": "Position projection from parsed intent and market snapshot",
                "dataQuality": "Simulation-only estimate",
                "adapter": "PositionProjectionModel",
                "sourceKind": "simulation_model",
                "scope": "safer_trade_projection",
                "timestamp": timestamp,
                "rawRef": "projection:position_model:v1",
            }
        ],
    }


def evaluate_trade_risk(
    intent: dict[str, Any],
    account_state: dict[str, Any],
    market_snapshot: dict[str, Any],
    positions: list[dict[str, Any]],
    mode: str,
    source_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    leverage = float(intent["leverage"])
    margin_usage = float(intent["marginUsagePct"])
    coverage_status = str((source_coverage or {}).get("status") or "partial")
    coverage_blocking = coverage_status in {"partial", "unavailable"} or bool(intent.get("coverageRequestedPartial"))
    replay_context = coverage_status == "replay"
    score = min(100, int(leverage * 6 + margin_usage * 0.45 + (18 if coverage_blocking else 8 if replay_context else 0)))
    if leverage >= 10 or margin_usage >= 60:
        score = max(score, 86)
    elif coverage_blocking:
        score = max(score, 54)
    decision = "block" if score >= 70 or coverage_blocking else "warn" if score >= 35 else "allow"
    risk_level = "critical" if score >= 80 else "high" if score >= 50 else "moderate" if score >= 25 else "low"

    top_risks = [
        {
            "id": "risk_leverage",
            "title": "Leverage risk",
            "severity": "critical" if leverage >= 10 else "moderate" if leverage > 3 else "low",
            "claim": (
                f"{int(leverage)}x leverage exceeds the pre-flight guard threshold for an AI agent action."
                if leverage > 3
                else f"{int(leverage)}x leverage stays within the guard threshold for a human-confirmed preview."
            ),
            "evidenceIds": ["ev_intent_001", "ev_market_001", "ev_policy_001"],
            "confidence": 0.94,
        },
        {
            "id": "risk_margin",
            "title": "Margin usage risk",
            "severity": "critical" if margin_usage >= 60 else "high" if margin_usage > 35 else "moderate" if margin_usage > 20 else "low",
            "claim": (
                f"The request would use {int(margin_usage)}% of available margin before human review."
                if margin_usage > 20
                else f"The request uses {int(margin_usage)}% of available margin, within the guard's preview range."
            ),
            "evidenceIds": ["ev_intent_001", "ev_account_001", "ev_policy_001"],
            "confidence": 0.9,
        },
        {
            "id": "risk_liquidation",
            "title": "Liquidation distance risk",
            "severity": "high" if score >= 70 else "moderate" if score >= 35 else "low",
            "claim": (
                "Projected liquidation distance is too narrow for a default agent execution path."
                if score >= 35
                else "Projected liquidation distance remains inside the preview-only guard range."
            ),
            "evidenceIds": ["ev_market_001", "ev_position_001", "ev_simulation_001"],
            "confidence": 0.82,
        },
    ]
    if coverage_blocking:
        top_risks.append(
            {
                "id": "risk_coverage",
                "title": "Evidence coverage gap",
                "severity": "high",
                "claim": "Some source coverage is partial, so missing data is unknown rather than safe.",
                "evidenceIds": ["ev_market_001", "ev_policy_001"],
                "confidence": 0.72,
            }
        )

    action_by_decision = {
        "allow": "Approve human-confirmed execution preview",
        "warn": "Require review before execution",
        "block": "Block execution and simulate safer trade",
    }
    reason_by_decision = {
        "allow": f"{int(leverage)}x leverage and {int(margin_usage)}% margin usage stay inside the guard preview policy; no autonomous execution is allowed.",
        "warn": f"{int(leverage)}x leverage or {int(margin_usage)}% margin usage exceeds the autonomous preview threshold and requires human review.",
        "block": f"{int(leverage)}x leverage and {int(margin_usage)}% margin usage exceed the guard policy for an autonomous agent action.",
    }
    allowed_by_decision = {
        "allow": ["Inspect evidence", "Preview human-confirmed execution", "Simulate safer trade", "Record assessment hash", "Verify assessment"],
        "warn": ["Inspect evidence", "Require human review", "Simulate safer trade", "Record assessment hash", "Verify assessment"],
        "block": ["Inspect evidence", "Simulate safer trade", "Record assessment hash", "Verify assessment"],
    }
    blocked_by_decision = {
        "allow": ["Auto-sign", "Transfer funds", "LLM-generated transaction execution", "Place order without human confirmation"],
        "warn": ["Place order until review", "Auto-sign", "Transfer funds", "LLM-generated transaction execution"],
        "block": ["Place order", "Auto-sign", "Transfer funds", "LLM-generated transaction execution"],
    }

    return {
        "decision": decision,
        "riskScore": score,
        "riskLevel": risk_level,
        "action": action_by_decision[decision],
        "reason": reason_by_decision[decision],
        "topRisks": top_risks,
        "allowedActions": allowed_by_decision[decision],
        "blockedActions": blocked_by_decision[decision],
    }


def safer_trade_simulation(intent: dict[str, Any], risk_before: int) -> dict[str, Any]:
    after = {
        **intent,
        "leverage": 3,
        "marginUsagePct": 15,
        "notionalUsd": max(250, int(float(intent.get("notionalUsd", 2500)) * 0.25)),
        "slippageBps": 15,
    }
    risk_after = 38 if risk_before >= 70 else 24
    return {
        "simulationId": f"sim_{_hash_object({'before': intent})[2:10]}",
        "before": intent,
        "after": after,
        "riskBefore": risk_before,
        "riskAfter": risk_after,
        "riskDelta": risk_after - risk_before,
        "explanation": "Reducing to 3x leverage and 15% available margin gives the agent a safer proposal that still requires human confirmation before execution.",
        "noBroadcast": True,
    }


def source_coverage_fixture(mode: str, intent: dict[str, Any]) -> dict[str, Any]:
    partial = bool(intent.get("coverageRequestedPartial")) or str(intent.get("market", "")).startswith("BTC")
    replay = mode == "demo_scenario" and not partial
    status = "partial" if partial else "replay" if replay else "full"
    return {
        "status": status,
        "unavailableSources": ["historical liquidation depth"] if partial else [],
        "unknownFields": ["deep liquidation depth", "full venue liquidity"] if partial else [],
        "explanation": (
            "Some read-only sources are partial; missing data is unknown, not safe."
            if partial
            else "Demo replay fixture is isolated from live execution and is not treated as live safety evidence."
            if replay
            else "Account, market, and position sources are available for this check."
        ),
        "sources": [
            {"name": "Injective account state", "status": "replay" if mode == "demo_scenario" else "simulated"},
            {"name": "Injective market snapshot", "status": "replay" if mode == "demo_scenario" else "simulated"},
            {"name": "Open positions", "status": "partial" if partial else "replay" if replay else "simulated"},
            {"name": "Proof verifier", "status": "available"},
        ],
        "modeSummary": "Demo replay fixture" if mode == "demo_scenario" else "Live proof with simulated market/account fixture",
    }


def combine_source_coverage(
    mode: str,
    intent: dict[str, Any],
    account_state: dict[str, Any],
    market_snapshot: dict[str, Any],
    positions_payload: dict[str, Any],
) -> dict[str, Any]:
    coverages = [
        account_state.get("sourceCoverage", {}),
        market_snapshot.get("sourceCoverage", {}),
        positions_payload.get("sourceCoverage", {}),
    ]
    status_order = {"full": 0, "replay": 1, "partial": 2, "unavailable": 3}
    worst = max((str(item.get("status") or "partial") for item in coverages), key=lambda value: status_order.get(value, 2))
    if mode == "demo_scenario" and worst == "full":
        worst = "replay"
    unavailable: list[str] = []
    unknown: list[str] = []
    sources: list[dict[str, str]] = []
    for coverage in coverages:
        unavailable.extend(str(item) for item in coverage.get("unavailableSources", []))
        unknown.extend(str(item) for item in coverage.get("unknownFields", []))
        sources.extend(item for item in coverage.get("sources", []) if isinstance(item, dict))
    if mode == "demo_scenario":
        unknown.append("fresh live execution data")
    explanation = (
        "All configured read-only Injective sources were available for this check."
        if worst == "full"
        else "Demo replay fixture is isolated from live execution and is not treated as live safety evidence."
        if worst == "replay"
        else "One or more read-only Injective sources are partial; missing data is unknown, not safe."
    )
    mode_summary = (
        "Demo replay fixture"
        if mode == "demo_scenario"
        else "Live read-only Injective sources"
        if worst == "full"
        else "Live proof with simulated market/account fixture"
    )
    return {
        "status": worst,
        "unavailableSources": sorted(set(unavailable)),
        "unknownFields": sorted(set(unknown)),
        "explanation": explanation,
        "sources": sources or source_coverage_fixture(mode, intent)["sources"],
        "modeSummary": mode_summary,
    }


def build_agent_audit(assessment: dict[str, Any]) -> dict[str, Any]:
    decision = assessment["decision"]
    return {
        "assessmentId": assessment["assessmentId"],
        "decision": decision,
        "allowedActions": decision["allowedActions"],
        "blockedActions": decision["blockedActions"],
        "llmBoundary": "The model explains; deterministic policy blocks unsafe execution paths before signing or order placement.",
        "agentIdentity": {
            "agentName": "InjectiveLens Agent Guard",
            "agentCardUrl": "/.well-known/agent-card.json",
            "registryUrl": "/agent-registration.json",
            "mcpUrl": "/mcp",
        },
        "toolTrace": tool_trace(assessment),
    }


def tool_trace(assessment: dict[str, Any]) -> list[dict[str, Any]]:
    decision = assessment["decision"]["decision"]
    score = assessment["decision"]["riskScore"]
    source_status = assessment["sourceCoverage"]["status"]
    proof_status = assessment["proof"]["status"]
    recorded = proof_status in {"recorded", "verified_matched"}
    timestamp = assessment.get("createdAt", FIXED_TIMESTAMP)
    evidence_ids = [item["id"] for item in assessment.get("evidence", [])]
    return [
        _trace_event(1, "ParseTradeIntent", "completed", "Natural-language request parsed into structured trade intent.", ["ev_intent_001"], timestamp),
        _trace_event(2, "NormalizeTradeParameters", "completed", "Market, side, order type, leverage, margin usage, notional, and slippage were normalized before scoring.", ["ev_intent_001"], timestamp),
        _trace_event(3, "GetAccountState", "completed", "Read-only account and subaccount context loaded or explicitly marked as simulated fallback.", ["ev_account_001"], timestamp),
        _trace_event(4, "GetMarketSnapshot", "completed", "Market mark price, oracle price, spread, funding, and leverage context loaded or explicitly marked as simulated fallback.", ["ev_market_001"], timestamp),
        _trace_event(5, "GetOpenPositions", "completed", "Position source returned partial/simulated coverage." if source_status == "partial" else "Open position source available.", ["ev_position_001"], timestamp),
        _trace_event(6, "EvaluateTradeRisk", "block" if decision == "block" else "allow", f"Policy decision {decision.upper()} with risk score {score}/100.", evidence_ids, timestamp),
        _trace_event(7, "BindEvidenceBundle", "completed", "Risk decision was bound to evidence ids before assessment hashing.", evidence_ids, timestamp),
        _trace_event(8, "SimulateSaferTrade", "completed", "Generated lower-leverage alternative without placing an order.", ["ev_simulation_001"], timestamp),
        _trace_event(9, "DecideExecutionBoundary", "block" if decision == "block" else "allow", "Unsafe execution actions are blocked; review, simulation, proof record, and verification remain allowed.", evidence_ids, timestamp),
        _trace_event(10, "GenerateAssessmentHash", "completed", "Assessment hash generated from request, parsed intent, decision, source coverage, and evidence ids.", evidence_ids, timestamp),
        _trace_event(11, "RecordAssessment", "completed" if recorded else "skipped", "Assessment hash has a recorded Injective testnet proof." if recorded else f"Proof status is {proof_status}; explicit confirmation is required before recording.", evidence_ids, timestamp),
        _trace_event(12, "VerifyAssessment", "completed" if proof_status == "verified_matched" else "skipped", "Local and recorded assessment hashes match." if proof_status == "verified_matched" else "Verification waits for a recorded proof.", evidence_ids, timestamp),
    ]


def history_records(latest: dict[str, Any] | None = None, assessment_history: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for assessment in [latest, *(assessment_history or [])]:
        if not assessment or not isinstance(assessment, dict):
            continue
        assessment_id = str(assessment.get("assessmentId") or "")
        if not assessment_id or assessment_id in seen:
            continue
        seen.add(assessment_id)
        records.append(history_record_from_assessment(assessment))
    return records


def history_record_from_assessment(assessment: dict[str, Any]) -> dict[str, Any]:
    mode = assessment["request"]["mode"]
    source_coverage = assessment.get("sourceCoverage", {})
    proof = assessment.get("proof", {})
    market_snapshot = assessment.get("marketSnapshot", {})
    return {
        "assessmentId": assessment["assessmentId"],
        "createdAt": assessment["createdAt"],
        "prompt": assessment["request"]["prompt"],
        "market": assessment["parseResult"]["tradeIntent"]["market"],
        "decision": assessment["decision"]["decision"],
        "riskScore": assessment["decision"]["riskScore"],
        "riskLevel": assessment["decision"]["riskLevel"],
        "dataMode": "demo_replay" if mode == "demo_scenario" else "live_read_only",
        "sourceMode": source_coverage.get("modeSummary") or ("Demo replay fixture" if mode == "demo_scenario" else "Live read-only"),
        "marketSource": market_snapshot.get("sourceKind") or "unknown",
        "simulatedMarket": str(market_snapshot.get("marketId") or "").startswith(SIMULATED_FIXTURE_PREFIX + ":"),
        "proofStatus": proof_status_label(proof),
        "proofRecorded": bool(proof.get("txHash")) and proof.get("status") in {"recorded", "verified_matched"},
        "proofVerified": proof.get("status") == "verified_matched",
        "txHash": proof.get("txHash") if proof.get("status") in {"recorded", "verified_matched"} else None,
        "topRisks": [risk["title"] for risk in assessment["decision"]["topRisks"][:3]],
    }


def proof_status_label(proof: dict[str, Any]) -> str:
    status = proof.get("status")
    if status == "ready_to_record":
        return "Assessment hash generated"
    if status == "pending":
        return "Awaiting proof recording"
    if status == "recorded":
        return "Proof recorded on Injective testnet"
    if status == "verified_matched":
        return "Proof verified · recorded hash matches"
    if status == "unavailable":
        return "Proof unavailable"
    if status == "verified_mismatch":
        return "Proof mismatch"
    return "Not recorded"


def _evidence_items(
    intent: dict[str, Any],
    mode: str,
    account_state: dict[str, Any] | None = None,
    market_snapshot: dict[str, Any] | None = None,
    positions_payload: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    evidence_mode = "demo_replay" if mode == "demo_scenario" else "live_read_only"
    account_evidence = (account_state or {}).get("evidence") or []
    market_evidence = (market_snapshot or {}).get("evidence") or []
    position_evidence = (positions_payload or {}).get("evidence") or []
    return [
        {
            "id": "ev_intent_001",
            "source": "Trade intent parser",
            "claim": f"{int(intent['leverage'])}x {intent['side']} {intent['market']}, {int(intent['marginUsagePct'])}% margin usage.",
            "mode": evidence_mode,
            "verification": "Parsed from natural-language request",
            "dataQuality": "Deterministic parse",
            "adapter": "DeterministicIntentParser",
            "sourceKind": "user_intent",
            "scope": "trade_intent",
            "timestamp": FIXED_TIMESTAMP,
            "rawRef": "parser:deterministic:v1",
        },
        account_evidence[0] if account_evidence else {
            "id": "ev_account_001",
            "source": "Injective account state",
            "claim": "Available margin is bounded; requested trade would consume a large share of the subaccount.",
            "mode": evidence_mode,
            "verification": "Read-only account/subaccount balance fixture",
            "dataQuality": "Demo replay" if mode == "demo_scenario" else "Live read-only ready",
            "adapter": "FixtureInjectiveReadOnlyAdapter",
            "sourceKind": "demo_replay_fixture" if mode == "demo_scenario" else "simulated_fixture",
            "scope": "account_state",
            "timestamp": FIXED_TIMESTAMP,
            "rawRef": "fixture:account_state:v1",
        },
        market_evidence[0] if market_evidence else {
            "id": "ev_market_001",
            "source": "Injective market snapshot",
            "claim": f"{intent['market']} market data is available for pre-flight evaluation.",
            "mode": evidence_mode,
            "verification": "Market mark price, max leverage, spread, and funding snapshot",
            "dataQuality": "Partial source coverage" if mode == "demo_scenario" else "Full source coverage",
            "adapter": "FixtureInjectiveReadOnlyAdapter",
            "sourceKind": "demo_replay_fixture" if mode == "demo_scenario" else "simulated_market_fixture",
            "scope": "market_context",
            "timestamp": FIXED_TIMESTAMP,
            "rawRef": "fixture:market_snapshot:v1",
        },
        position_evidence[0] if position_evidence else {
            "id": "ev_position_001",
            "source": "Injective position model",
            "claim": "Simulated liquidation distance is below the configured safety threshold.",
            "mode": "simulated",
            "verification": "Position projection from parsed intent and market snapshot",
            "dataQuality": "Simulation-only estimate",
            "adapter": "PositionProjectionModel",
            "sourceKind": "simulation_model",
            "scope": "position_projection",
            "timestamp": FIXED_TIMESTAMP,
            "rawRef": "projection:position_model:v1",
        },
        {
            "id": "ev_policy_001",
            "source": "Guard policy threshold",
            "claim": "Autonomous execution is blocked above the guard's leverage, margin usage, or coverage-risk thresholds.",
            "mode": "simulated",
            "verification": "Deterministic guard policy: max autonomous leverage 3x, max margin usage 20%, unknown coverage is not safe",
            "dataQuality": "Policy rule, not chain data",
            "adapter": "InjectiveLensGuardPolicy",
            "sourceKind": "policy_rule",
            "scope": "guard_policy",
            "timestamp": FIXED_TIMESTAMP,
            "rawRef": "policy:pre_execution_guard:v1",
        },
        {
            "id": "ev_simulation_001",
            "source": "Safer trade simulation",
            "claim": "The guard proposes a 3x leverage, 15% margin alternative and still requires human confirmation.",
            "mode": "simulated",
            "verification": "Simulation-only safer action; no order, transfer, signing, or broadcast",
            "dataQuality": "Simulation result, not an Injective execution",
            "adapter": "SaferTradeSimulation",
            "sourceKind": "simulation_model",
            "scope": "safer_alternative",
            "timestamp": FIXED_TIMESTAMP,
            "rawRef": "simulation:safer_trade:v1",
        },
    ]


def subaccount_kind(subaccount_id: str) -> str:
    return "simulation_placeholder" if subaccount_id == DEFAULT_SUBACCOUNT_ID else "provided_subaccount"


def _trace_event(
    step: int,
    tool: str,
    status: str,
    summary: str,
    evidence_ids: list[str],
    timestamp: str,
) -> dict[str, Any]:
    return {
        "step": step,
        "tool": tool,
        "status": status,
        "summary": summary,
        "evidenceIds": evidence_ids,
        "actionType": "blocked" if status == "block" else "allowed" if status in {"allow", "completed"} else "skipped",
        "timestamp": timestamp,
    }


def _hash_object(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "0x" + hashlib.sha256(payload).hexdigest()
