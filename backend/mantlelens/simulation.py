from __future__ import annotations

from typing import Any

from .hashutil import stable_hash


def simulate_approval_revoke(
    assessment: dict[str, Any],
    *,
    action_id: str | None = None,
) -> dict[str, Any]:
    before = dict(assessment["subScores"])
    after = dict(before)
    after["approvalRisk"] = max(0, before.get("approvalRisk", 0) - 60)
    before_score = assessment["walletRiskScore"]
    after_score = _weighted_score(after)
    evidence_ids = _evidence_for_type(assessment, "approval")
    payload = {
        "simulationId": f"sim_approval_{assessment['assessmentId']}",
        "assessmentId": assessment["assessmentId"],
        "simulationType": "approval_revoke_impact",
        "actionId": action_id or "act_simulate_revoke_approval",
        "executionMode": "simulation_only",
        "before": {
            "walletRiskScore": before_score,
            "subScores": before,
        },
        "after": {
            "walletRiskScore": after_score,
            "subScores": after,
        },
        "scoreDelta": round(after_score - before_score, 2),
        "summary": "Simulated approval review lowers approval risk. No revoke transaction is created.",
        "evidenceIds": evidence_ids,
        "transactionCreated": False,
    }
    payload["simulationHash"] = stable_hash(payload)
    return payload


def simulate_portfolio_adjustment(
    assessment: dict[str, Any],
    *,
    action_id: str | None = None,
) -> dict[str, Any]:
    before = dict(assessment["subScores"])
    after = dict(before)
    after["rwaYieldRisk"] = max(0, before.get("rwaYieldRisk", 0) - 30)
    after["assetConcentrationRisk"] = max(0, before.get("assetConcentrationRisk", 0) - 20)
    before_score = assessment["walletRiskScore"]
    after_score = _weighted_score(after)
    evidence_ids = _evidence_for_type(assessment, "rwa_yield") or _evidence_for_type(assessment, "concentration")
    payload = {
        "simulationId": f"sim_portfolio_{assessment['assessmentId']}",
        "assessmentId": assessment["assessmentId"],
        "simulationType": "portfolio_adjustment",
        "actionId": action_id or "act_simulate_portfolio_adjustment",
        "executionMode": "simulation_only",
        "before": {
            "walletRiskScore": before_score,
            "subScores": before,
        },
        "after": {
            "walletRiskScore": after_score,
            "subScores": after,
        },
        "scoreDelta": round(after_score - before_score, 2),
        "summary": "Simulated portfolio adjustment lowers concentration and Mantle yield exposure. No trade is created.",
        "evidenceIds": evidence_ids,
        "transactionCreated": False,
    }
    payload["simulationHash"] = stable_hash(payload)
    return payload


def _weighted_score(sub_scores: dict[str, Any]) -> float:
    weights = {
        "approvalRisk": 0.35,
        "suspiciousTransferRisk": 0.25,
        "assetConcentrationRisk": 0.20,
        "rwaYieldRisk": 0.15,
        "defiExposureStub": 0.05,
    }
    return round(sum(float(sub_scores.get(key, 0)) * weight for key, weight in weights.items()), 2)


def _evidence_for_type(assessment: dict[str, Any], risk_type: str) -> list[str]:
    for risk in assessment.get("topRisks", []):
        if risk.get("type") == risk_type:
            return list(risk.get("evidenceIds", []))
    return []
