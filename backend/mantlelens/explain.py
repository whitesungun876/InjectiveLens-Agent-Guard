from __future__ import annotations

from typing import Any


def rule_based_explanation(
    assessment: dict[str, Any],
    evidence: list[dict[str, Any]],
    *,
    fallback_reason: str = "rule_fallback",
) -> dict[str, Any]:
    evidence_by_id = {item["evidenceId"]: item for item in evidence}
    top_risks = assessment.get("topRisks", [])
    lines = [
        f"Your wallet risk level is {assessment['riskLevel']} with score {assessment['walletRiskScore']}/100.",
        f"This is based on a {assessment.get('dataStatus', 'PARTIAL_OR_UNKNOWN')} scan, so unavailable indexed data is not treated as safe.",
    ]
    claims = []

    for risk in top_risks[:3]:
        ids = [evidence_id for evidence_id in risk.get("evidenceIds", []) if evidence_id in evidence_by_id]
        if not ids:
            continue
        lines.append(f"- {risk['claimText']} Evidence: {', '.join(ids)}.")
        claims.append({"claimText": risk["claimText"], "evidenceIds": ids})

    for action in assessment.get("suggestedActions", [])[:2]:
        mode = action.get("executionMode", "view_only").replace("_", "-")
        lines.append(f"Suggested action: {action['label']} ({mode}).")

    return {
        "assessmentId": assessment["assessmentId"],
        "mode": "rule_fallback",
        "explanation": "\n".join(lines),
        "claims": claims,
        "claimGuardPassed": True,
        "fallbackReason": fallback_reason,
    }
