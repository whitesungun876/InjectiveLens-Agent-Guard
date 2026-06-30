from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .evidence import build_evidence_bundle, validate_evidence_binding
from .hashutil import stable_hash


WEIGHTS = {
    "approvalRisk": 0.35,
    "suspiciousTransferRisk": 0.25,
    "assetConcentrationRisk": 0.20,
    "rwaYieldRisk": 0.15,
    "defiExposureStub": 0.05,
}

SUPPLEMENTAL_CATEGORY_WEIGHTS = {
    "approval": WEIGHTS["approvalRisk"],
    "transfer": WEIGHTS["suspiciousTransferRisk"],
    "concentration": WEIGHTS["assetConcentrationRisk"],
    "high_value_exposure": WEIGHTS["assetConcentrationRisk"],
    "token_security": 0.10,
    "source_coverage": 0.0,
    "stale_data": 0.0,
    "wallet_activity": 0.0,
    "rwa_yield": WEIGHTS["rwaYieldRisk"],
    "defi": WEIGHTS["defiExposureStub"],
    "data_quality": 0.0,
}

STABLECOINS = {"USDC", "USDT", "USDY", "mUSD"}

METRIC_META = {
    "approvalRisk": {
        "label": "Approval Risk",
        "riskTypes": {"approval"},
        "calculationMode": "active_allowance_confirmed",
    },
    "suspiciousTransferRisk": {
        "label": "Suspicious Transfer Risk",
        "riskTypes": {"transfer"},
        "calculationMode": "bounded_indexed_transfer_logs",
    },
    "assetConcentrationRisk": {
        "label": "Asset Concentration Risk",
        "riskTypes": {"concentration"},
        "calculationMode": "known_token_or_provider_balances",
    },
    "defiExposureStub": {
        "label": "DeFi Exposure Stub",
        "riskTypes": {"defi"},
        "calculationMode": "known_lp_symbol_stub",
    },
    "rwaYieldRisk": {
        "label": "RWA/Yield Risk",
        "riskTypes": {"rwa_yield"},
        "calculationMode": "mantle_yield_token_exposure",
    },
}


def evaluate_wallet_risk(raw_scan: dict[str, Any]) -> dict[str, Any]:
    fixture_id = raw_scan.get("fixtureId", "wallet")
    wallet = raw_scan["wallet"]
    evidence_items = _augmented_evidence(raw_scan)
    balances = _tool_items(raw_scan, "getKnownTokenBalances", "balances")
    native = _tool_value(raw_scan, "getNativeBalance", "balance")
    if native:
        balances = [native] + balances
    approvals = _tool_items(raw_scan, "getTokenApprovals", "approvals")
    transfers = _tool_items(raw_scan, "getTransferLogs", "transfers")
    token_security = _tool_items(raw_scan, "getTokenSecurity", "tokens")
    rwa_exposure = _tool_value(raw_scan, "getRwaYieldExposure", "rwaYieldExposure") or {}

    assessment_id = f"assessment_{fixture_id}"
    evidence_bundle = build_evidence_bundle(assessment_id, evidence_items)
    evidence_by_id = {item["evidenceId"]: item for item in evidence_bundle["evidence"]}

    approval_score, approval_risk = _score_approvals(approvals, evidence_by_id)
    transfer_score, transfer_risk = _score_transfers(transfers, evidence_by_id)
    concentration_score, concentration_risk = _score_concentration(balances, evidence_by_id)
    high_value_score, high_value_risk = _score_high_value_exposure(balances, evidence_by_id, raw_scan)
    token_security_score, token_security_risk = _score_token_security(token_security, evidence_by_id, raw_scan)
    rwa_score, rwa_risk = _score_rwa_yield(rwa_exposure, balances, evidence_by_id)
    defi_score, defi_risk = _score_defi_stub(balances, evidence_by_id)
    data_status, data_quality_risk = _score_data_quality(raw_scan, evidence_by_id)
    stale_score, stale_risk = _score_stale_data(evidence_bundle["evidence"], evidence_by_id, raw_scan)
    wallet_activity_score, wallet_activity_risk = _score_wallet_activity(raw_scan, evidence_by_id)

    all_risks = [
        risk
        for risk in [
            approval_risk,
            transfer_risk,
            concentration_risk,
            high_value_risk,
            token_security_risk,
            rwa_risk,
            defi_risk,
            data_quality_risk,
            stale_risk,
            wallet_activity_risk,
        ]
        if risk is not None
    ]
    top_risks = list(all_risks)
    top_risks.sort(key=lambda item: (_severity_rank(item["severity"]), item["scoreImpact"]), reverse=True)
    top_risks = top_risks[:3]
    for index, risk in enumerate(top_risks, start=1):
        risk["rank"] = index

    sub_scores = {
        "approvalRisk": approval_score,
        "suspiciousTransferRisk": transfer_score,
        "assetConcentrationRisk": concentration_score,
        "defiExposureStub": defi_score,
        "rwaYieldRisk": rwa_score,
    }
    wallet_risk_score = round(sum(sub_scores[key] * WEIGHTS[key] for key in WEIGHTS), 2)
    risk_level = _risk_level(wallet_risk_score)
    if approval_score >= 85:
        wallet_risk_score = max(wallet_risk_score, 85)
        risk_level = "Critical"
    elif approval_score >= 80 or transfer_score >= 75 or rwa_score >= 60:
        risk_level = _max_level(risk_level, "High")
    if data_status == "PARTIAL_OR_UNKNOWN" and risk_level == "Low":
        risk_level = "Moderate"

    suggested_actions = _suggest_actions(top_risks, _first_evidence_ids(raw_scan))
    _attach_recommended_actions(top_risks, suggested_actions)
    risk_engine = _risk_engine_report(
        all_risks=all_risks,
        top_risks=top_risks,
        sub_scores=sub_scores,
        wallet_risk_score=wallet_risk_score,
        risk_level=risk_level,
        data_status=data_status,
        data_confidence=_data_confidence(raw_scan),
        supplemental_scores={
            "highValueExposureRisk": high_value_score,
            "tokenSecurityRisk": token_security_score,
            "sourceCoverageRisk": data_quality_risk["scoreImpact"] if data_quality_risk else 0,
            "staleDataRisk": stale_score,
            "walletActivityRisk": wallet_activity_score,
        },
    )
    assessment = {
        "schemaVersion": "mantlelens.wallet_assessment.v1",
        "assessmentId": assessment_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "chainId": raw_scan["chainId"],
        "wallet": wallet,
        "walletRiskScore": wallet_risk_score,
        "riskLevel": risk_level,
        "riskLevelV2": _risk_level_v2(wallet_risk_score),
        "dataConfidence": _data_confidence(raw_scan),
        "dataStatus": data_status,
        "topRisks": top_risks,
        "subScores": sub_scores,
        "metricResults": _metric_results(sub_scores, top_risks, raw_scan),
        "scoreBreakdown": risk_engine["scoreBreakdown"],
        "riskEngine": risk_engine,
        "dataCompleteness": raw_scan["dataCompleteness"],
        "evidenceBundleHash": evidence_bundle["evidenceBundleHash"],
        "recommendationHash": stable_hash(suggested_actions),
        "suggestedActions": suggested_actions,
        "dataMode": raw_scan["dataMode"],
        "decisionType": _decision_type(top_risks, data_status),
        "actionType": suggested_actions[0]["actionType"] if suggested_actions else "NO_ACTION",
    }
    assessment["topRisksHash"] = stable_hash(top_risks)
    assessment["assessmentHash"] = stable_hash(
        {
            "assessmentId": assessment["assessmentId"],
            "walletHash": wallet["walletHash"],
            "walletRiskScore": assessment["walletRiskScore"],
            "riskLevel": assessment["riskLevel"],
            "topRisksHash": assessment["topRisksHash"],
            "evidenceBundleHash": assessment["evidenceBundleHash"],
            "recommendationHash": assessment["recommendationHash"],
            "dataMode": assessment["dataMode"],
        }
    )
    validate_evidence_binding(assessment, evidence_bundle["evidence"])
    return {
        "assessment": assessment,
        "evidenceBundle": evidence_bundle,
    }


def _tool_items(raw_scan: dict[str, Any], tool_name: str, key: str) -> list[dict[str, Any]]:
    return raw_scan["toolOutputs"][tool_name]["output"].get(key, [])


def _tool_value(raw_scan: dict[str, Any], tool_name: str, key: str) -> Any:
    return raw_scan["toolOutputs"][tool_name]["output"].get(key)


def _risk(
    *,
    risk_id: str,
    category: str,
    severity: str,
    title: str,
    explanation: str,
    score_impact: int,
    evidence_ids: list[str],
    source_status: str,
    recommended_safe_actions: list[str],
    confidence: float,
    is_blocking: bool = False,
    unknowns: list[str] | None = None,
    limitations: list[str] | None = None,
) -> dict[str, Any]:
    capped_score = _cap_score_for_confidence(score_impact, confidence)
    contribution = round(capped_score * SUPPLEMENTAL_CATEGORY_WEIGHTS.get(category, 0.0), 2)
    return {
        "riskId": risk_id,
        "risk_id": risk_id,
        "type": category,
        "category": category,
        "title": title,
        "severity": severity,
        "severity_v2": "Medium" if severity == "Moderate" else severity,
        "claimText": explanation,
        "explanation": explanation,
        "scoreImpact": capped_score,
        "score_impact": capped_score,
        "scoreContribution": contribution,
        "score_contribution": contribution,
        "confidence": round(max(0.0, min(1.0, confidence)), 2),
        "evidenceIds": evidence_ids,
        "evidence_ids": evidence_ids,
        "sourceStatus": source_status,
        "source_status": source_status,
        "recommendedSafeActions": recommended_safe_actions,
        "recommended_safe_actions": recommended_safe_actions,
        "isBlocking": is_blocking,
        "is_blocking": is_blocking,
        "unknowns": unknowns or [],
        "limitations": limitations or [],
    }


def _score_approvals(
    approvals: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
) -> tuple[int, dict[str, Any] | None]:
    active = [item for item in approvals if item.get("isActive")]
    if not active:
        return 0, None

    score = 0
    selected = active[0]
    for item in active:
        item_score = 0
        malicious_spender = item.get("isMalicious") or str(item.get("spenderRisk", "")).lower() in {
            "malicious",
            "blocked",
            "scam",
        }
        unknown_spender = not item.get("spenderLabel")
        if malicious_spender:
            item_score = 100
        elif item.get("isUnlimited") and unknown_spender and item.get("allowanceUsd", 0) > 500:
            item_score = max(item_score, 80)
        elif unknown_spender:
            item_score += 10
            allowance_usd = item.get("allowanceUsd") or 0
            if allowance_usd > 20000:
                item_score += 60
            elif allowance_usd > 5000:
                item_score += 40
            elif allowance_usd > 1000:
                item_score += 20
        item_score = min(item_score, 100)
        if item_score > score:
            score = item_score
            selected = item

    if score <= 0:
        return 0, None
    severity = "Critical" if score >= 85 else "High" if score >= 60 else "Moderate"
    evidence_ids = _existing_ids([selected["evidenceId"], _balance_evidence_for_token(selected["token"], evidence_by_id)], evidence_by_id)
    malicious_selected = selected.get("isMalicious") or str(selected.get("spenderRisk", "")).lower() in {
        "malicious",
        "blocked",
        "scam",
    }
    risk_id = "risk_approval_malicious_active" if malicious_selected else "risk_approval_unknown_unlimited" if selected.get("isUnlimited") else "risk_approval_active_unknown"
    explanation = f"{selected['token']} has an active {'unlimited ' if selected.get('isUnlimited') else ''}approval to {_spender_claim(selected)}."
    unknowns = []
    if not selected.get("spenderLabel"):
        unknowns.append("spender label unavailable")
    if selected.get("isUnlimited"):
        unknowns.append("approval allowance is unlimited until user revokes or spender spends it")
    return score, _risk(
        risk_id=risk_id,
        category="approval",
        severity=severity,
        title="Active unlimited approval" if selected.get("isUnlimited") else "Active unknown approval",
        explanation=explanation,
        score_impact=score,
        evidence_ids=evidence_ids,
        source_status=_row_source_status(selected),
        recommended_safe_actions=["simulate revoke impact", "review spender", "manual revoke only from user wallet if supported"],
        confidence=_risk_confidence(evidence_ids, evidence_by_id, _row_source_status(selected)),
        is_blocking=malicious_selected,
        unknowns=unknowns,
        limitations=["Approval events alone are not enough; active allowance confirmation is required."],
    )


def _score_transfers(
    transfers: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
) -> tuple[int, dict[str, Any] | None]:
    score = 0
    selected: dict[str, Any] | None = None
    for item in transfers:
        pattern = item.get("pattern", "")
        item_score = 0
        if "lookalike" in pattern or item.get("transferType") == "dust":
            item_score = max(item_score, 75)
        if "fake" in pattern or item.get("transferType") == "fake_token":
            item_score = max(item_score, 50)
        if "new_recipient" in pattern:
            item_score = max(item_score, 25)
        if item_score > score:
            score = item_score
            selected = item
    if not selected:
        return 0, None
    severity = "High" if score >= 75 else "Moderate"
    explanation = "A tiny incoming transfer from a lookalike address may be address poisoning." if score >= 75 else "A recent outgoing transfer went to a new recipient."
    evidence_ids = _existing_ids([selected["evidenceId"]], evidence_by_id)
    return score, _risk(
        risk_id="risk_transfer_address_poisoning" if score >= 75 else "risk_transfer_new_recipient",
        category="transfer",
        severity=severity,
        title="Dust transfer / address poisoning" if score >= 75 else "New transfer counterparty",
        explanation=explanation,
        score_impact=score,
        evidence_ids=evidence_ids,
        source_status=_row_source_status(selected),
        recommended_safe_actions=["mark counterparty suspicious", "review transfer log"],
        confidence=_risk_confidence(evidence_ids, evidence_by_id, _row_source_status(selected)),
        unknowns=["bounded transfer history may miss older transfers"],
        limitations=["P0/P1 scans bounded recent logs over configured or indexed tokens only."],
    )


def _score_concentration(
    balances: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
) -> tuple[int, dict[str, Any] | None]:
    valued = [item for item in balances if item.get("valueUsd", 0) > 0]
    total = sum(item["valueUsd"] for item in valued)
    if total <= 0 or not valued:
        return 0, None
    ranked = sorted(valued, key=lambda item: item["valueUsd"], reverse=True)
    top = ranked[0]
    top_pct = top["valueUsd"] / total * 100
    top3_pct = sum(item["valueUsd"] for item in ranked[:3]) / total * 100
    score = 0
    if top_pct >= 95:
        score = 80
    elif top_pct >= 85:
        score = 65
    elif top_pct >= 70:
        score = 45
    elif top_pct >= 50:
        score = 20
    if top3_pct > 90:
        score = min(score + 20, 100)
    if top_pct > 85 and top["symbol"] not in STABLECOINS:
        score = max(score, 60)
    if score < 45:
        return score, None
    severity = "High" if score >= 60 else "Moderate"
    evidence_ids = _existing_ids([top.get("evidenceId")], evidence_by_id)
    return score, _risk(
        risk_id="risk_asset_concentration",
        category="concentration",
        severity=severity,
        title="Token concentration",
        explanation=f"{top['symbol']} is {top_pct:.1f}% of the known-token portfolio.",
        score_impact=score,
        evidence_ids=evidence_ids,
        source_status=_row_source_status(top),
        recommended_safe_actions=["review concentration exposure", "simulate portfolio adjustment"],
        confidence=_risk_confidence(evidence_ids, evidence_by_id, _row_source_status(top)),
        unknowns=["unknown-token inventory may be incomplete"],
        limitations=["Concentration uses known-token or provider inventory balances only."],
    )


def _score_high_value_exposure(
    balances: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
    raw_scan: dict[str, Any],
) -> tuple[int, dict[str, Any] | None]:
    valued = [item for item in balances if item.get("valueUsd", 0) > 0]
    if not valued:
        return 0, None
    top = max(valued, key=lambda item: item.get("valueUsd", 0))
    value = float(top.get("valueUsd") or 0)
    score = 0
    if value >= 50000:
        score = 70
    elif value >= 10000:
        score = 55
    elif value >= 5000:
        score = 45
    if score <= 0:
        return 0, None
    severity = "High" if score >= 60 else "Moderate"
    evidence_ids = _existing_ids([top.get("evidenceId")], evidence_by_id)
    source_status = _coverage_status(raw_scan, ["knownTokenBalances", "fullTokenInventory"])
    return score, _risk(
        risk_id="risk_high_value_token_exposure",
        category="high_value_exposure",
        severity=severity,
        title="High-value token exposure",
        explanation=f"{top['symbol']} has a high-value wallet exposure of about ${value:,.2f}.",
        score_impact=score,
        evidence_ids=evidence_ids,
        source_status=source_status,
        recommended_safe_actions=["inspect token", "review portfolio exposure"],
        confidence=_risk_confidence(evidence_ids, evidence_by_id, source_status),
        unknowns=["prices are context only and can change"],
        limitations=["Price sources are used for exposure sizing, not investment advice."],
    )


def _score_token_security(
    tokens: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
    raw_scan: dict[str, Any],
) -> tuple[int, dict[str, Any] | None]:
    risky = [item for item in tokens if item.get("status") == "risky" or item.get("riskFlags")]
    unknown = [item for item in tokens if item.get("status") == "unknown"]
    selected = risky[0] if risky else unknown[0] if unknown else None
    if not selected:
        return 0, None
    score = 70 if risky else 25
    severity = "High" if risky else "Moderate"
    evidence_ids = _existing_ids([selected.get("evidenceId")], evidence_by_id)
    source_status = _coverage_status(raw_scan, ["tokenSecurity"])
    symbol = selected.get("symbol") or selected.get("tokenAddress") or "token"
    flags = ", ".join(selected.get("riskFlags") or []) or "unverified/unknown security status"
    return score, _risk(
        risk_id="risk_token_security_signal" if risky else "risk_token_security_unknown",
        category="token_security",
        severity=severity,
        title="Suspicious or unverified token",
        explanation=f"{symbol} has token security signals requiring review: {flags}.",
        score_impact=score,
        evidence_ids=evidence_ids,
        source_status=source_status,
        recommended_safe_actions=["inspect token", "check source coverage"],
        confidence=_risk_confidence(evidence_ids, evidence_by_id, source_status),
        unknowns=["GoPlus clean or missing signals do not guarantee token safety"],
        limitations=["GoPlus token security is an advisory signal, not a proof of safety."],
    )


def _score_rwa_yield(
    rwa_exposure: dict[str, Any],
    balances: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
) -> tuple[int, dict[str, Any] | None]:
    if not rwa_exposure:
        return 0, None
    exposure_pct = float(rwa_exposure.get("mETHPct", 0)) + float(rwa_exposure.get("cmETHPct", 0))
    score = 0
    if exposure_pct >= 70:
        score = 60
    elif exposure_pct >= 50:
        score = 40
    elif exposure_pct >= 30:
        score = 20
    if rwa_exposure.get("liquidityWarning"):
        score = max(score, 60)
    cmeth_value = next((item.get("valueUsd", 0) for item in balances if item.get("symbol") == "cmETH"), 0)
    if cmeth_value > 500:
        score = max(score, 60)
    if score <= 0:
        return 0, None
    evidence_ids = _existing_ids(rwa_exposure.get("evidenceIds", []), evidence_by_id)
    severity = "High" if score >= 60 else "Moderate"
    source_status = "partial" if rwa_exposure.get("liquidityWarning") else "available"
    return score, _risk(
        risk_id="risk_rwa_yield_exposure",
        category="rwa_yield",
        severity=severity,
        title="Mantle yield token exposure",
        explanation="mETH and cmETH make up a large part of the known-token portfolio.",
        score_impact=score,
        evidence_ids=evidence_ids,
        source_status=source_status,
        recommended_safe_actions=["simulate portfolio adjustment", "inspect token"],
        confidence=_risk_confidence(evidence_ids, evidence_by_id, source_status),
        unknowns=["yield-token liquidity can change; this is not yield advice"],
        limitations=["mETH/cmETH are Mantle yield assets; this is not yield advice."],
    )


def _score_defi_stub(
    balances: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
) -> tuple[int, dict[str, Any] | None]:
    lp_tokens = [item for item in balances if "LP" in item.get("symbol", "").upper()]
    if not lp_tokens:
        return 0, None
    highest = max(lp_tokens, key=lambda item: item.get("valueUsd", 0))
    score = 50 if highest.get("valueUsd", 0) > 5000 else 25 if highest.get("valueUsd", 0) > 500 else 0
    if score <= 0:
        return 0, None
    evidence_ids = _existing_ids([highest.get("evidenceId")], evidence_by_id)
    return score, _risk(
        risk_id="risk_defi_stub_lp",
        category="defi",
        severity="Moderate",
        title="DeFi LP token exposure",
        explanation=f"{highest['symbol']} is detected as a known LP/protocol token in the P0 DeFi stub.",
        score_impact=score,
        evidence_ids=evidence_ids,
        source_status=_row_source_status(highest),
        recommended_safe_actions=["inspect token", "review portfolio exposure"],
        confidence=_risk_confidence(evidence_ids, evidence_by_id, _row_source_status(highest)),
        unknowns=["full DeFi position parsing is not part of P2.3"],
        limitations=["Full DeFi position parsing is P1/P2."],
    )


def _score_data_quality(
    raw_scan: dict[str, Any],
    evidence_by_id: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any] | None]:
    completeness = raw_scan.get("dataCompleteness", {})
    critical_keys = ["nativeBalance", "knownTokenBalances", "approvalEvents", "transferLogs"]
    critical_values = [completeness.get(key) for key in critical_keys]
    coverage_ids = _coverage_evidence_ids(evidence_by_id)
    if all(value == "unavailable" for value in critical_values):
        return "PARTIAL_OR_UNKNOWN", _risk(
            risk_id="risk_data_unknown",
            category="source_coverage",
            severity="Moderate",
            title="Source coverage unavailable",
            explanation="Critical wallet data sources are unavailable, so the scan cannot be treated as safe.",
            score_impact=25,
            evidence_ids=coverage_ids,
            source_status="source_failed",
            recommended_safe_actions=["check source coverage", "rescan later"],
            confidence=0.55,
            unknowns=["native balance, approvals, or transfer history may be missing"],
            limitations=["Missing data is unknown, not normal."],
        )
    if any(value in {"partial", "unavailable", "not_supported_p0"} for value in completeness.values()):
        incomplete = sorted(key for key, value in completeness.items() if value in {"partial", "unavailable", "not_supported_p0"})
        return "PARTIAL_OR_UNKNOWN", _risk(
            risk_id="risk_source_coverage_partial",
            category="source_coverage",
            severity="Moderate",
            title="Partial source coverage",
            explanation="Some wallet data is partial or unavailable, so missing data remains unknown rather than safe.",
            score_impact=15,
            evidence_ids=coverage_ids,
            source_status="partial",
            recommended_safe_actions=["check source coverage", "rescan later"],
            confidence=0.65,
            unknowns=incomplete[:6],
            limitations=["Source coverage risk reduces confidence; it does not assert hidden wallet danger."],
        )
    return "FULL", None


def _score_stale_data(
    evidence_items: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
    raw_scan: dict[str, Any],
) -> tuple[int, dict[str, Any] | None]:
    stale_ids: list[str] = []
    missing_timestamps: list[str] = []
    now = datetime.now(UTC)
    live_or_stale = raw_scan.get("dataMode") == "live"
    for item in evidence_items:
        evidence_id = item.get("evidenceId")
        if not evidence_id:
            continue
        if item.get("dataQuality") == "stale":
            stale_ids.append(evidence_id)
            live_or_stale = True
            continue
        timestamp = item.get("timestamp")
        if not timestamp:
            if raw_scan.get("dataMode") == "live":
                missing_timestamps.append(evidence_id)
            continue
        parsed = _parse_timestamp(timestamp)
        if parsed and raw_scan.get("dataMode") == "live" and (now - parsed).days > 30:
            stale_ids.append(evidence_id)
    if not live_or_stale or not stale_ids and not missing_timestamps:
        return 0, None
    evidence_ids = _existing_ids(stale_ids[:3] or missing_timestamps[:3] or _coverage_evidence_ids(evidence_by_id), evidence_by_id)
    score = 20 if stale_ids else 10
    return score, _risk(
        risk_id="risk_stale_or_undated_evidence",
        category="stale_data",
        severity="Moderate",
        title="Stale or undated evidence",
        explanation="Some live evidence is stale or missing timestamps, so the scan confidence is reduced.",
        score_impact=score,
        evidence_ids=evidence_ids,
        source_status="partial",
        recommended_safe_actions=["rescan later", "check source coverage"],
        confidence=0.6,
        unknowns=["provider timestamps may be old or unavailable"],
        limitations=["Stale data affects confidence and should not be interpreted as safety."],
    )


def _score_wallet_activity(
    raw_scan: dict[str, Any],
    evidence_by_id: dict[str, dict[str, Any]],
) -> tuple[int, dict[str, Any] | None]:
    completeness = raw_scan.get("dataCompleteness", {})
    transfer_status = completeness.get("transferLogs")
    history_status = completeness.get("transactionHistory")
    if transfer_status not in {"partial", "unavailable", "not_supported_p0"} and history_status not in {"partial", "unavailable", "not_supported_p0"}:
        return 0, None
    evidence_ids = _coverage_evidence_ids(evidence_by_id)
    source_status = "source_failed" if transfer_status == "unavailable" or history_status == "unavailable" else "partial"
    score = 20 if source_status == "source_failed" else 12
    return score, _risk(
        risk_id="risk_wallet_activity_unknown",
        category="wallet_activity",
        severity="Moderate",
        title="Wallet activity coverage unknown",
        explanation="Transfer or transaction history is incomplete, so activity-based risk cannot be fully ruled out.",
        score_impact=score,
        evidence_ids=evidence_ids,
        source_status=source_status,
        recommended_safe_actions=["check source coverage", "rescan later"],
        confidence=0.6 if source_status == "source_failed" else 0.7,
        unknowns=["approval and transfer history may be incomplete"],
        limitations=["Unavailable activity history is unknown, not safe."],
    )


def _augmented_evidence(raw_scan: dict[str, Any]) -> list[dict[str, Any]]:
    evidence = [dict(item) for item in raw_scan.get("evidence", [])]
    existing_ids = {item.get("evidenceId") for item in evidence}
    coverage = raw_scan.get("dataCompleteness", {})
    source_statuses = raw_scan.get("sourceAvailability", {})
    incomplete = {
        key: value
        for key, value in coverage.items()
        if value in {"partial", "unavailable", "not_supported_p0", "source_failed", "unknown"}
    }
    limited_sources = {
        name: {"status": source.get("status")}
        for name, source in source_statuses.items()
        if isinstance(source, dict) and source.get("status") in {"partial", "unavailable", "source_failed", "unknown"}
    }
    if not incomplete and not limited_sources:
        return evidence
    evidence_id = f"ev_source_coverage_{stable_hash({'coverage': incomplete, 'sources': limited_sources})[2:14]}"
    if evidence_id not in existing_ids:
        evidence.append(
            {
                "evidenceId": evidence_id,
                "type": "source_coverage",
                "claimText": "Some configured data sources returned partial, unavailable, or unsupported coverage.",
                "source": "MantleLens Source Coverage",
                "endpoint": "scan:dataCompleteness",
                "rawData": {
                    "incompleteData": incomplete,
                    "sourceStatuses": limited_sources,
                    "missingDataIsSafe": False,
                },
                "timestamp": None,
                "dataQuality": "coverage",
                "limitation": "Coverage evidence records uncertainty only; it does not imply hidden risk or safety.",
            }
        )
    return evidence


def _coverage_evidence_ids(evidence_by_id: dict[str, dict[str, Any]]) -> list[str]:
    ids = [
        evidence_id
        for evidence_id, evidence in evidence_by_id.items()
        if evidence.get("type") == "source_coverage"
    ]
    if ids:
        return sorted(ids)
    return sorted(evidence_by_id)[:1]


def _risk_engine_report(
    *,
    all_risks: list[dict[str, Any]],
    top_risks: list[dict[str, Any]],
    sub_scores: dict[str, int],
    wallet_risk_score: float,
    risk_level: str,
    data_status: str,
    data_confidence: float,
    supplemental_scores: dict[str, int],
) -> dict[str, Any]:
    metric_contributions = [
        {
            "metricId": metric_id,
            "score": score,
            "weight": WEIGHTS[metric_id],
            "weightedContribution": round(score * WEIGHTS[metric_id], 2),
        }
        for metric_id, score in sub_scores.items()
    ]
    risk_contributions = [
        {
            "riskId": risk["riskId"],
            "category": risk["category"],
            "severity": risk["severity"],
            "scoreImpact": risk["scoreImpact"],
            "scoreContribution": risk["scoreContribution"],
            "confidence": risk["confidence"],
            "evidenceIds": risk["evidenceIds"],
        }
        for risk in all_risks
    ]
    red_flags = [
        {"rule": "active approval risk floor", "condition": "approvalRisk >= 85", "level": "Critical"}
        if sub_scores.get("approvalRisk", 0) >= 85
        else None,
        {"rule": "high evidence risk floor", "condition": "approvalRisk >= 80 or transferRisk >= 75 or rwaYieldRisk >= 60", "level": "High"}
        if sub_scores.get("approvalRisk", 0) >= 80 or sub_scores.get("suspiciousTransferRisk", 0) >= 75 or sub_scores.get("rwaYieldRisk", 0) >= 60
        else None,
    ]
    return {
        "schemaVersion": "mantlelens.risk_engine.v2",
        "status": data_status,
        "dataConfidence": data_confidence,
        "allRisks": all_risks,
        "supplementalScores": supplemental_scores,
        "scoreBreakdown": {
            "schemaVersion": "mantlelens.score_breakdown.v1",
            "method": "weighted_metric_sum_with_red_flag_overrides",
            "totalScore": wallet_risk_score,
            "riskLevel": risk_level,
            "riskLevelV2": _risk_level_v2(wallet_risk_score),
            "dataConfidence": data_confidence,
            "metricContributions": metric_contributions,
            "riskContributions": risk_contributions,
            "redFlagOverrides": [item for item in red_flags if item],
            "topRiskIds": [risk["riskId"] for risk in top_risks],
            "weightedMetricSum": round(sum(item["weightedContribution"] for item in metric_contributions), 2),
        },
    }


def _attach_recommended_actions(top_risks: list[dict[str, Any]], actions: list[dict[str, Any]]) -> None:
    by_evidence: dict[str, list[str]] = {}
    for action in actions:
        for evidence_id in action.get("evidenceIds", []):
            by_evidence.setdefault(evidence_id, []).append(action["actionType"])
    for risk in top_risks:
        action_types: list[str] = []
        for evidence_id in risk.get("evidenceIds", []):
            action_types.extend(by_evidence.get(evidence_id, []))
        if action_types:
            deduped = list(dict.fromkeys(action_types))
            risk["recommendedSafeActions"] = deduped
            risk["recommended_safe_actions"] = deduped


def _coverage_status(raw_scan: dict[str, Any], keys: list[str]) -> str:
    values = [raw_scan.get("dataCompleteness", {}).get(key) for key in keys]
    if any(value in {"unavailable", "source_failed"} for value in values):
        return "source_failed"
    if any(value in {"partial", "not_supported_p0", "unknown"} for value in values):
        return "partial"
    return "available"


def _row_source_status(row: dict[str, Any]) -> str:
    status = str(row.get("sourceStatus") or row.get("source_status") or row.get("dataCoverage") or row.get("data_coverage") or "available")
    if status in {"unavailable", "source_failed"}:
        return "source_failed"
    if status in {"partial", "known_token_only", "known-token-only", "bounded", "unknown"} or "partial" in status:
        return "partial"
    return "available"


def _risk_confidence(evidence_ids: list[str], evidence_by_id: dict[str, dict[str, Any]], source_status: str) -> float:
    if not evidence_ids:
        return 0.0
    if any(evidence_id not in evidence_by_id for evidence_id in evidence_ids):
        return 0.0
    base = 0.95
    if source_status == "partial":
        base = 0.78
    elif source_status in {"unavailable", "source_failed", "unknown"}:
        base = 0.58
    if any((evidence_by_id[evidence_id].get("dataQuality") in {"missing", "coverage"}) for evidence_id in evidence_ids):
        base = min(base, 0.68)
    return round(base, 2)


def _cap_score_for_confidence(score: int, confidence: float) -> int:
    if confidence <= 0:
        return min(score, 25)
    if confidence < 0.55:
        return min(score, 35)
    if confidence < 0.70:
        return min(score, 50)
    return score


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _data_confidence(raw_scan: dict[str, Any]) -> float:
    values = list(raw_scan.get("dataCompleteness", {}).values())
    scored = [value for value in values if value != "not_supported_p0"]
    if not scored:
        return 0.5
    points = 0.0
    for value in scored:
        if value == "available":
            points += 1.0
        elif value == "partial":
            points += 0.65
        elif value in {"unavailable", "source_failed", "unknown"}:
            points += 0.0
    return round(max(0.5, min(1.0, points / len(scored))), 2)


def _metric_results(
    sub_scores: dict[str, int],
    top_risks: list[dict[str, Any]],
    raw_scan: dict[str, Any],
) -> list[dict[str, Any]]:
    first_evidence_ids = _first_evidence_ids(raw_scan)
    results: list[dict[str, Any]] = []
    for metric_id, score in sub_scores.items():
        meta = METRIC_META[metric_id]
        related_risks = [
            risk for risk in top_risks
            if risk.get("type") in meta["riskTypes"]
        ]
        evidence_ids = []
        limitations: list[str] = []
        for risk in related_risks:
            evidence_ids.extend(risk.get("evidenceIds", []))
            limitations.extend(risk.get("limitations", []))
        if not evidence_ids:
            evidence_ids = first_evidence_ids[:1]
        results.append(
            {
                "metricId": metric_id,
                "label": meta["label"],
                "score": score,
                "weight": WEIGHTS[metric_id],
                "weightedContribution": round(score * WEIGHTS[metric_id], 2),
                "severity": _risk_level(score),
                "evidenceIds": list(dict.fromkeys(evidence_ids)),
                "calculationMode": meta["calculationMode"],
                "limitations": list(dict.fromkeys(limitations)),
            }
        )
    return results


def _suggest_actions(
    top_risks: list[dict[str, Any]],
    fallback_evidence_ids: list[str],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for risk in top_risks:
        if risk["type"] == "approval":
            if risk["severity"] == "Critical":
                actions.append(
                    {
                        "actionId": "act_review_critical_approval",
                        "actionType": "REVIEW_APPROVAL",
                        "label": "Review approval before any user-signed action",
                        "executionMode": "view_only",
                        "evidenceIds": risk["evidenceIds"],
                    }
                )
            else:
                actions.append(
                    {
                        "actionId": "act_simulate_revoke_approval",
                        "actionType": "SIMULATE_REVOKE_APPROVAL",
                        "label": "Simulate revoke impact",
                        "executionMode": "simulation_only",
                        "evidenceIds": risk["evidenceIds"],
                    }
                )
        elif risk["type"] == "transfer":
            actions.append(
                {
                    "actionId": "act_mark_address_suspicious",
                    "actionType": "MARK_ADDRESS_SUSPICIOUS",
                    "label": "Mark counterparty as suspicious",
                    "executionMode": "view_only",
                    "evidenceIds": risk["evidenceIds"],
                }
            )
        elif risk["type"] == "rwa_yield":
            actions.append(
                {
                    "actionId": "act_simulate_portfolio_adjustment",
                    "actionType": "SIMULATE_REDUCE_METH_INCREASE_MUSD",
                    "label": "Simulate lower mETH/cmETH exposure",
                    "executionMode": "simulation_only",
                    "evidenceIds": risk["evidenceIds"],
                }
            )
        elif risk["type"] == "concentration":
            actions.append(
                {
                    "actionId": "act_review_concentration",
                    "actionType": "REVIEW_DEFI_EXPOSURE",
                    "label": "Review concentration exposure",
                    "executionMode": "view_only",
                    "evidenceIds": risk["evidenceIds"],
                }
            )
        elif risk["type"] == "data_quality":
            actions.append(
                {
                    "actionId": "act_record_partial_assessment",
                    "actionType": "RECORD_ASSESSMENT_ONLY",
                    "label": "Record partial assessment only",
                    "executionMode": "view_only",
                    "evidenceIds": risk["evidenceIds"],
                }
            )
    return actions


def _decision_type(top_risks: list[dict[str, Any]], data_status: str) -> str:
    if not top_risks:
        return "SIMULATE_ONLY" if data_status == "PARTIAL_OR_UNKNOWN" else "SAFE"
    first_risk = top_risks[0]
    first = first_risk["type"]
    if first_risk["severity"] == "Critical":
        return "PAUSE"
    if first in {"data_quality", "source_coverage", "stale_data", "wallet_activity"}:
        return "SIMULATE_ONLY"
    if first == "approval":
        return "REVIEW_APPROVAL"
    if first == "transfer":
        return "FLAG_SUSPICIOUS_TRANSFER"
    if first in {"rwa_yield", "concentration"}:
        return "SIMULATE_PORTFOLIO_CHANGE"
    return "WATCH"


def _risk_level(score: float) -> str:
    if score <= 20:
        return "Low"
    if score <= 45:
        return "Moderate"
    if score <= 70:
        return "High"
    return "Critical"


def _risk_level_v2(score: float) -> str:
    value = _risk_level(score)
    return "Medium" if value == "Moderate" else value


def _severity_rank(level: str) -> int:
    return {"Low": 1, "Moderate": 2, "High": 3, "Critical": 4}.get(level, 0)


def _max_level(left: str, right: str) -> str:
    return left if _severity_rank(left) >= _severity_rank(right) else right


def _spender_claim(approval: dict[str, Any]) -> str:
    spender_label = approval.get("spenderLabel")
    if approval.get("isMalicious") or str(approval.get("spenderRisk", "")).lower() in {"malicious", "blocked", "scam"}:
        return "a spender flagged as malicious"
    if not spender_label:
        return "an unknown spender"
    return str(spender_label)


def _balance_evidence_for_token(token: str, evidence_by_id: dict[str, dict[str, Any]]) -> str | None:
    token_lower = token.lower()
    for evidence_id, evidence in evidence_by_id.items():
        text = evidence.get("claimText", "").lower()
        if token_lower in text and evidence.get("type") == "balance":
            return evidence_id
    return None


def _existing_ids(candidate_ids: list[str | None], evidence_by_id: dict[str, dict[str, Any]]) -> list[str]:
    ids = [evidence_id for evidence_id in candidate_ids if evidence_id and evidence_id in evidence_by_id]
    return list(dict.fromkeys(ids))


def _first_evidence_ids(raw_scan: dict[str, Any]) -> list[str]:
    evidence = raw_scan.get("evidence", [])
    if evidence:
        return [evidence[0]["evidenceId"]]
    return []
