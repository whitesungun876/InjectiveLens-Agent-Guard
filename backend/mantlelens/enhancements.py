from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any

from .config import MantleLensConfig
from .hashutil import stable_hash
from .inventory import HistoryPageOptions
from .live_adapters import (
    EtherscanV2Client,
    GoPlusClient,
    JsonHttpClient,
    MantleRpcClient,
    SourceUnavailable,
    _address_from_topic,
    _hex_to_int,
)


def detect_nft_approvals(payload: dict[str, Any]) -> dict[str, Any]:
    approvals = _list(payload.get("nftApprovals"))
    approvals.extend(_tool_list(payload, "getNftApprovals", "nftApprovals"))
    if not approvals:
        try:
            approvals.extend(_indexed_nft_approvals(payload))
        except Exception:
            approvals = []
    normalized = []
    for item in approvals:
        token_standard = item.get("tokenStandard") or item.get("standard") or "ERC721"
        is_active = bool(item.get("isActive", True))
        normalized.append(
            {
                "tokenStandard": token_standard,
                "tokenAddress": item.get("tokenAddress"),
                "operator": item.get("operator") or item.get("spender"),
                "approvalType": item.get("approvalType") or "setApprovalForAll",
                "isActive": is_active,
                "evidenceIds": _evidence_ids(item),
                "txHash": item.get("txHash"),
            }
        )
    if not normalized:
        return _module_unavailable(
            "nft_approval_detection",
            "NFT approval indexer is not configured; absence of data is unknown, not safe.",
        )
    active = [item for item in normalized if item["isActive"]]
    return {
        "module": "nft_approval_detection",
        "status": "available",
        "items": normalized,
        "activeApprovalCount": len(active),
        "fallbackUsed": False,
        "limitations": ["ERC-721/ERC-1155 approvals require indexed events and current owner/operator state."],
    }


def prepare_manual_revoke(payload: dict[str, Any]) -> dict[str, Any]:
    approval = payload.get("approval") if isinstance(payload.get("approval"), dict) else None
    if approval is None:
        approval = _first_active_approval(payload)
    if not approval:
        return _module_unavailable(
            "manual_revoke",
            "No active ERC20 approval was provided; revoke transaction request cannot be prepared.",
        )
    token_address = str(approval.get("tokenAddress") or "")
    spender = str(approval.get("spender") or "")
    if not _is_address(token_address) or not _is_address(spender):
        return _module_unavailable(
            "manual_revoke",
            "tokenAddress and spender are required to prepare a revoke transaction request.",
        )
    chain_id = int(payload.get("chainId") or _assessment(payload).get("chainId") or 5000)
    tx_request = {
        "chainId": chain_id,
        "to": token_address.lower(),
        "data": "0x095ea7b3" + _abi_address(spender) + "0" * 64,
        "value": "0x0",
        "method": "approve(address,uint256)",
        "args": {"spender": spender.lower(), "allowance": "0"},
    }
    return {
        "module": "manual_revoke",
        "status": "manual_signature_required",
        "txRequest": tx_request,
        "broadcasted": False,
        "transactionCreated": False,
        "fallbackUsed": False,
        "safety": {
            "serverDoesNotSign": True,
            "serverDoesNotBroadcast": True,
            "requiresUserWalletConfirmation": True,
        },
        "evidenceIds": _evidence_ids(approval),
        "limitations": ["The app prepares a revoke request only; the user wallet must inspect and sign manually."],
    }


def parse_defi_positions(payload: dict[str, Any]) -> dict[str, Any]:
    positions = _list(payload.get("defiPositions"))
    inventory = payload.get("inventory") if isinstance(payload.get("inventory"), dict) else {}
    for token in _list(inventory.get("tokens")):
        symbol = str(token.get("symbol") or "")
        upper = symbol.upper()
        if any(marker in upper for marker in ("LP", "STAKED", "VAULT", "AAVE", "CURVE", "PENDLE")):
            positions.append(
                {
                    "protocol": token.get("protocol") or "unknown_protocol",
                    "positionType": "lp_or_protocol_token",
                    "symbol": symbol,
                    "tokenAddress": token.get("tokenAddress"),
                    "valueUsd": token.get("valueUsd", 0),
                    "evidenceIds": _evidence_ids(token),
                    "parsingMode": "token_symbol_inventory_heuristic",
                }
            )
    if not positions:
        return {
            "module": "defi_deep_parsing",
            "status": "no_positions_detected",
            "positions": [],
            "fallbackUsed": True,
            "limitations": ["No DeFi parser/provider returned protocol positions; this is not proof that no DeFi exposure exists."],
        }
    return {
        "module": "defi_deep_parsing",
        "status": "available",
        "positions": positions,
        "positionCount": len(positions),
        "fallbackUsed": False,
        "limitations": ["Heuristic positions should be verified against protocol-specific adapters before production use."],
    }


def evaluate_goplus_full_security(payload: dict[str, Any]) -> dict[str, Any]:
    evidence = _list(payload.get("evidence"))
    approvals = _approval_items(payload)
    token_signals = []
    for item in evidence:
        if item.get("type") != "token_security":
            continue
        raw = item.get("rawData") if isinstance(item.get("rawData"), dict) else {}
        token_signals.append(
            {
                "evidenceId": item.get("evidenceId"),
                "riskFlags": raw.get("riskFlags", []),
                "securitySignals": raw.get("securitySignals", {}),
                "limitation": item.get("limitation"),
            }
        )
    approval_signals = []
    for approval in approvals:
        risk = str(approval.get("spenderRisk") or "").lower()
        if approval.get("isMalicious") or risk in {"malicious", "blocked", "scam"}:
            approval_signals.append(
                {
                    "spender": approval.get("spender"),
                    "tokenAddress": approval.get("tokenAddress"),
                    "spenderRisk": risk or "malicious",
                    "evidenceIds": _evidence_ids(approval),
                }
            )
    live_signals = _goplus_live_signals(payload)
    approval_signals.extend(live_signals["approvalSignals"])
    address_signals = _list(payload.get("addressSignals"))
    address_signals.extend(live_signals["addressSignals"])
    if not token_signals and not approval_signals and not address_signals:
        return {
            "module": "goplus_full_security",
            "status": "partial",
            "tokenSignals": [],
            "approvalSignals": [],
            "addressSignals": [],
            "fallbackUsed": True,
            "limitations": ["GoPlus full address/approval security was unavailable; clean cannot be inferred."],
        }
    return {
        "module": "goplus_full_security",
        "status": "available",
        "tokenSignals": token_signals,
        "approvalSignals": approval_signals,
        "addressSignals": address_signals,
        "fallbackUsed": False,
        "limitations": ["GoPlus results are advisory security signals, not guaranteed wallet safety."],
    }


def simulate_transaction(
    payload: dict[str, Any],
    *,
    config: MantleLensConfig | None = None,
    http: JsonHttpClient | None = None,
) -> dict[str, Any]:
    config = config or MantleLensConfig.from_env()
    tx_request = payload.get("txRequest") if isinstance(payload.get("txRequest"), dict) else None
    if not tx_request:
        tx_request = prepare_manual_revoke(payload).get("txRequest")
    if not isinstance(tx_request, dict):
        return _module_unavailable(
            "real_tx_simulation",
            "No transaction request is available to simulate.",
        )
    precheck = _tx_precheck(tx_request)
    simulation_id = f"txsim_{stable_hash(tx_request)[2:14]}"
    if not config.tx_simulation_rpc_url:
        return {
            "module": "real_tx_simulation",
            "status": "provider_unavailable",
            "simulationId": simulation_id,
            "provider": None,
            "txRequest": tx_request,
            "precheck": precheck,
            "transactionCreated": False,
            "broadcasted": False,
            "fallbackUsed": True,
            "limitations": ["No live transaction simulation provider is configured; this is a local precheck only."],
        }
    provider_tx = _provider_tx_request(payload, tx_request)
    if not provider_tx.get("from"):
        return {
            "module": "real_tx_simulation",
            "status": "provider_unavailable",
            "simulationId": simulation_id,
            "provider": config.tx_simulation_provider,
            "txRequest": tx_request,
            "precheck": precheck,
            "transactionCreated": False,
            "broadcasted": False,
            "fallbackUsed": True,
            "limitations": ["A from address is required before a live simulation provider can be called."],
        }
    try:
        provider_response = (http or JsonHttpClient(timeout=config.tx_simulation_timeout_sec, retries=0)).post_json(
            config.tx_simulation_rpc_url,
            _simulation_rpc_payload(config.tx_simulation_rpc_method, provider_tx, simulation_id),
            timeout=config.tx_simulation_timeout_sec,
        )
    except SourceUnavailable as exc:
        return _tx_provider_error(config, tx_request, precheck, simulation_id, str(exc))
    except Exception as exc:
        return _tx_provider_error(config, tx_request, precheck, simulation_id, str(exc))
    if provider_response.get("error"):
        return _tx_provider_error(config, tx_request, precheck, simulation_id, str(provider_response["error"]))
    result = provider_response.get("result", provider_response)
    provider_hash = stable_hash({"tx": provider_tx, "providerResult": result})
    return {
        "module": "real_tx_simulation",
        "status": "simulated",
        "simulationId": f"{simulation_id}_{provider_hash[2:10]}",
        "provider": config.tx_simulation_provider,
        "txRequest": tx_request,
        "precheck": precheck,
        "simulationResult": _compact_provider_result(result),
        "transactionCreated": False,
        "broadcasted": False,
        "fallbackUsed": False,
        "limitations": ["Provider simulation completed without broadcasting; users must still inspect wallet prompts manually."],
    }


def build_social_share_card(payload: dict[str, Any]) -> dict[str, Any]:
    assessment = _assessment(payload)
    risk_level = assessment.get("riskLevel", "Unknown")
    score = assessment.get("walletRiskScore", "?")
    card = {
        "title": "MantleLens Wallet Guard",
        "riskLevel": risk_level,
        "walletRiskScore": score,
        "dataConfidence": assessment.get("dataConfidence"),
        "topRiskCount": len(_list(assessment.get("topRisks"))),
        "assessmentHash": assessment.get("assessmentHash"),
        "disclaimer": "Not financial advice. Missing indexed data is unknown, not safe.",
    }
    return {
        "module": "social_share_card",
        "status": "available",
        "card": card,
        "shareText": f"MantleLens scan: {risk_level} risk, score {score}. Not financial advice.",
        "posted": False,
        "fallbackUsed": False,
        "limitations": ["The API prepares share content only; it does not post to social networks."],
    }


def record_reputation_feedback(payload: dict[str, Any]) -> dict[str, Any]:
    assessment = _assessment(payload)
    feedback = str(payload.get("feedback") or "reviewed")
    record = {
        "assessmentHash": assessment.get("assessmentHash"),
        "walletHash": (assessment.get("wallet") or {}).get("walletHash"),
        "feedback": feedback,
        "createdAt": datetime.now(UTC).isoformat(),
    }
    record_hash = stable_hash(record)
    return {
        "module": "erc8004_reputation_feedback",
        "status": "local_recorded",
        "recordHash": record_hash,
        "record": record,
        "onchainSubmitted": False,
        "fallbackUsed": True,
        "limitations": ["ERC-8004 reputation feedback is stored locally unless a reputation endpoint/contract is configured."],
    }


def enhancement_summary(payload: dict[str, Any]) -> dict[str, Any]:
    modules = [
        detect_nft_approvals(payload),
        prepare_manual_revoke(payload),
        parse_defi_positions(payload),
        evaluate_goplus_full_security(payload),
        simulate_transaction(payload),
        build_social_share_card(payload),
        record_reputation_feedback({**payload, "feedback": "reviewed"}),
    ]
    return {
        "status": "available",
        "modules": modules,
        "moduleCount": len(modules),
        "safety": {
            "noAutoRevoke": True,
            "noServerSigning": True,
            "noTradeOrSwap": True,
        },
    }


def _module_unavailable(module: str, reason: str) -> dict[str, Any]:
    return {
        "module": module,
        "status": "unavailable",
        "items": [],
        "fallbackUsed": True,
        "unavailableReason": reason,
        "limitations": [reason],
    }


def _assessment(payload: dict[str, Any]) -> dict[str, Any]:
    assessment = payload.get("assessment")
    return assessment if isinstance(assessment, dict) else {}


def _tool_list(payload: dict[str, Any], tool_name: str, output_key: str) -> list[dict[str, Any]]:
    tool_outputs = payload.get("toolOutputs") if isinstance(payload.get("toolOutputs"), dict) else {}
    output = tool_outputs.get(tool_name, {}).get("output") if isinstance(tool_outputs.get(tool_name), dict) else {}
    return _list(output.get(output_key) if isinstance(output, dict) else None)


def _approval_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    approvals = _list(payload.get("approvals"))
    approvals.extend(_tool_list(payload, "getTokenApprovals", "approvals"))
    history = payload.get("history") if isinstance(payload.get("history"), dict) else {}
    approval_history = history.get("approvalHistory") if isinstance(history.get("approvalHistory"), dict) else {}
    approvals.extend(_list(approval_history.get("items")))
    return approvals


def _first_active_approval(payload: dict[str, Any]) -> dict[str, Any] | None:
    approvals = _approval_items(payload)
    for approval in approvals:
        if approval.get("isActive"):
            return approval
    return approvals[0] if approvals else None


def _list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _evidence_ids(item: dict[str, Any]) -> list[str]:
    evidence_ids = item.get("evidenceIds")
    if isinstance(evidence_ids, list):
        return [str(value) for value in evidence_ids if value]
    evidence_id = item.get("evidenceId")
    return [str(evidence_id)] if evidence_id else []


def _abi_address(address: str) -> str:
    return address.lower().replace("0x", "").rjust(64, "0")


def _is_address(value: str) -> bool:
    return value.startswith("0x") and len(value) == 42 and all(char in "0123456789abcdefABCDEF" for char in value[2:])


def _indexed_nft_approvals(payload: dict[str, Any]) -> list[dict[str, Any]]:
    config = MantleLensConfig.from_env()
    assessment = _assessment(payload)
    wallet = assessment.get("wallet") if isinstance(assessment.get("wallet"), dict) else {}
    owner = str(payload.get("walletAddress") or wallet.get("address") or "")
    if not _is_address(owner) or not config.etherscan_v2_api_key:
        return []
    page_options = _history_options(payload)
    http = JsonHttpClient(timeout=config.live_request_timeout_sec, retries=config.live_request_retries)
    etherscan = EtherscanV2Client(config, http)
    try:
        page = etherscan.nft_approval_for_all_logs_paginated(owner.lower(), page_options)
    except Exception:
        return []
    rpc = MantleRpcClient(config.effective_rpc_url, http) if config.effective_rpc_url else None
    approvals: list[dict[str, Any]] = []
    for row in page.rows:
        token_address = str(row.get("address") or "").lower()
        topics = row.get("topics") or []
        if not _is_address(token_address) or len(topics) < 3:
            continue
        operator = _address_from_topic(str(topics[2]))
        event_active = _hex_to_int(str(row.get("data") or "0x0")) > 0
        active = event_active
        active_state = "event_value_only"
        if rpc is not None:
            try:
                active = rpc.nft_is_approved_for_all(token_address, owner.lower(), operator)
                active_state = "confirmed_by_rpc_isApprovedForAll"
            except Exception:
                active_state = "rpc_confirmation_unavailable"
        approvals.append(
            {
                "tokenStandard": "ERC721_OR_ERC1155",
                "tokenAddress": token_address,
                "operator": operator,
                "approvalType": "setApprovalForAll",
                "isActive": bool(active),
                "eventActive": bool(event_active),
                "activeStatus": active_state,
                "evidenceIds": [],
                "txHash": row.get("transactionHash"),
                "blockNumber": row.get("blockNumber"),
                "source": "etherscan_v2_logs",
                "pageInfo": page.page_info,
            }
        )
    return approvals


def _history_options(payload: dict[str, Any]) -> HistoryPageOptions:
    raw = payload.get("historyOptions") if isinstance(payload.get("historyOptions"), dict) else {}
    return HistoryPageOptions(
        page_size=int(raw.get("pageSize") or 100),
        max_pages=int(raw.get("maxPages") or 2),
        from_block=int(raw.get("fromBlock") or 0),
        to_block=raw.get("toBlock") or "latest",
        sort=str(raw.get("sort") or "desc"),
    )


def _goplus_live_signals(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    config = MantleLensConfig.from_env()
    assessment = _assessment(payload)
    wallet = assessment.get("wallet") if isinstance(assessment.get("wallet"), dict) else {}
    owner = str(payload.get("walletAddress") or wallet.get("address") or "")
    if not _is_address(owner) or not config.goplus_api_key:
        return {"addressSignals": [], "approvalSignals": []}
    http = JsonHttpClient(timeout=config.live_request_timeout_sec, retries=config.live_request_retries)
    client = GoPlusClient(config, http)
    address_signals: list[dict[str, Any]] = []
    approval_signals: list[dict[str, Any]] = []
    try:
        address_security = client.address_security(owner.lower())
    except Exception:
        address_security = {}
    if address_security:
        risk_flags = [
            key
            for key, value in address_security.items()
            if str(value).lower() in {"1", "true", "yes"} and key not in {"data_source"}
        ]
        address_signals.append(
            {
                "address": owner.lower(),
                "source": "goplus_address_security",
                "riskFlags": risk_flags,
                "raw": address_security,
            }
        )
    try:
        approval_security = client.approval_security(owner.lower())
    except Exception:
        approval_security = {}
    rows = approval_security.get(owner.lower()) or approval_security.get(owner) or approval_security.get("result") or approval_security
    if isinstance(rows, dict):
        rows = rows.get("approval_list") or rows.get("approvals") or rows.get("tokens") or []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            risk_flags = [
                key
                for key, value in row.items()
                if str(value).lower() in {"1", "true", "yes"} and key.startswith(("is_", "malicious", "risky"))
            ]
            approval_signals.append(
                {
                    "spender": row.get("spender") or row.get("spender_address") or row.get("approved_address"),
                    "tokenAddress": row.get("token_address") or row.get("contract_address"),
                    "spenderRisk": "risky" if risk_flags else "unknown",
                    "riskFlags": risk_flags,
                    "source": "goplus_approval_security_v2",
                    "evidenceIds": [],
                }
            )
    return {"addressSignals": address_signals, "approvalSignals": approval_signals}


def _tx_precheck(tx_request: dict[str, Any]) -> dict[str, bool]:
    return {
        "chainIdPresent": bool(tx_request.get("chainId")),
        "toPresent": _is_address(str(tx_request.get("to") or "")),
        "calldataPresent": str(tx_request.get("data") or "").startswith("0x"),
        "valuePresent": str(tx_request.get("value") or "0x0").startswith("0x"),
    }


def _provider_tx_request(payload: dict[str, Any], tx_request: dict[str, Any]) -> dict[str, Any]:
    assessment = _assessment(payload)
    wallet = assessment.get("wallet") if isinstance(assessment.get("wallet"), dict) else {}
    provider_tx = {
        "from": tx_request.get("from") or payload.get("from") or wallet.get("address"),
        "to": tx_request.get("to"),
        "value": tx_request.get("value") or "0x0",
        "data": tx_request.get("data") or "0x",
    }
    for key in ("gas", "gasPrice", "maxFeePerGas", "maxPriorityFeePerGas"):
        if tx_request.get(key) is not None:
            provider_tx[key] = tx_request[key]
    return {key: value for key, value in provider_tx.items() if value is not None}


def _simulation_rpc_payload(method: str, provider_tx: dict[str, Any], simulation_id: str) -> dict[str, Any]:
    if method == "alchemy_simulateExecution":
        params = ["FLAT", provider_tx, "latest"]
    else:
        params = [provider_tx, "latest"]
    return {
        "id": simulation_id,
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
    }


def _tx_provider_error(
    config: MantleLensConfig,
    tx_request: dict[str, Any],
    precheck: dict[str, bool],
    simulation_id: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "module": "real_tx_simulation",
        "status": "provider_error",
        "simulationId": simulation_id,
        "provider": config.tx_simulation_provider,
        "txRequest": tx_request,
        "precheck": precheck,
        "transactionCreated": False,
        "broadcasted": False,
        "fallbackUsed": True,
        "providerError": reason,
        "limitations": ["The configured transaction simulation provider failed; failed simulation is unknown, not safe."],
    }


def _compact_provider_result(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"rawResult": result}
    allowed = {
        "status",
        "success",
        "gasUsed",
        "gas_used",
        "transaction",
        "trace",
        "assetChanges",
        "asset_changes",
        "balanceChanges",
        "balance_changes",
        "stateChanges",
        "state_changes",
        "error",
    }
    compact = {key: copy.deepcopy(value) for key, value in result.items() if key in allowed}
    return compact or {"rawResult": copy.deepcopy(result)}
