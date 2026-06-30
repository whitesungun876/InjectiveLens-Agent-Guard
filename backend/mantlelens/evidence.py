from __future__ import annotations

import copy
from typing import Any

from .hashutil import stable_hash


class EvidenceBindingError(ValueError):
    """Raised when a risk or action claim is not backed by known evidence."""


def normalize_evidence(evidence_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in evidence_items:
        cloned = copy.deepcopy(item)
        cloned.setdefault("limitation", None)
        if cloned.get("type") == "approval":
            cloned["allowanceConfirmed"] = _approval_allowance_confirmed(cloned)
        if cloned.get("type") == "transfer" and not cloned.get("txHash"):
            cloned["txHash"] = _transfer_tx_hash(cloned)
        hash_payload = {
            "evidenceId": cloned.get("evidenceId"),
            "type": cloned.get("type"),
            "claimText": cloned.get("claimText"),
            "source": cloned.get("source"),
            "endpoint": cloned.get("endpoint"),
            "rawData": cloned.get("rawData", {}),
            "txHash": cloned.get("txHash"),
            "allowanceConfirmed": cloned.get("allowanceConfirmed"),
            "timestamp": cloned.get("timestamp"),
            "dataQuality": cloned.get("dataQuality"),
            "limitation": cloned.get("limitation"),
        }
        cloned["evidenceHash"] = stable_hash(hash_payload)
        normalized.append(cloned)
    return normalized


def build_evidence_bundle(
    assessment_id: str,
    evidence_items: list[dict[str, Any]],
) -> dict[str, Any]:
    normalized = normalize_evidence(evidence_items)
    evidence_ids = [item["evidenceId"] for item in normalized]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise EvidenceBindingError(f"Duplicate evidenceId in assessment {assessment_id}")
    bundle_payload = {
        "assessmentId": assessment_id,
        "evidenceHashes": sorted(item["evidenceHash"] for item in normalized),
    }
    return {
        "assessmentId": assessment_id,
        "evidence": normalized,
        "evidenceBundleHash": stable_hash(bundle_payload),
        "evidenceCount": len(normalized),
    }


def validate_evidence_binding(
    assessment: dict[str, Any],
    evidence_items: list[dict[str, Any]],
) -> None:
    report = evidence_binding_report(assessment, evidence_items)
    if report["orphanClaimCount"]:
        raise EvidenceBindingError("Orphan claims blocked: " + "; ".join(report["orphanClaims"]))


def evidence_binding_report(
    assessment: dict[str, Any],
    evidence_items: list[dict[str, Any]],
) -> dict[str, Any]:
    known_ids = {item["evidenceId"] for item in evidence_items}
    orphan_claims: list[str] = []

    for item in evidence_items:
        if item.get("type") == "transfer" and not item.get("txHash"):
            orphan_claims.append(f"{item.get('evidenceId')}: transfer evidence missing txHash")
        if item.get("type") == "approval" and item.get("allowanceConfirmed") is None:
            orphan_claims.append(f"{item.get('evidenceId')}: approval evidence missing allowanceConfirmed")

    risks_to_check = list(assessment.get("topRisks", []))
    for risk in (assessment.get("riskEngine") or {}).get("allRisks", []):
        if risk not in risks_to_check:
            risks_to_check.append(risk)

    for risk in risks_to_check:
        evidence_ids = risk.get("evidenceIds") or []
        if not evidence_ids:
            orphan_claims.append(risk.get("riskId", risk.get("claimText", "<unknown risk>")))
            continue
        missing = [evidence_id for evidence_id in evidence_ids if evidence_id not in known_ids]
        if missing:
            orphan_claims.append(f"{risk.get('riskId')}: missing {', '.join(missing)}")

    for action in assessment.get("suggestedActions", []):
        evidence_ids = action.get("evidenceIds") or []
        if not evidence_ids:
            orphan_claims.append(action.get("actionId", action.get("label", "<unknown action>")))
            continue
        missing = [evidence_id for evidence_id in evidence_ids if evidence_id not in known_ids]
        if missing:
            orphan_claims.append(f"{action.get('actionId')}: missing {', '.join(missing)}")

    return {
        "status": "fail" if orphan_claims else "pass",
        "evidenceCount": len(evidence_items),
        "topRiskCount": len(assessment.get("topRisks", [])),
        "suggestedActionCount": len(assessment.get("suggestedActions", [])),
        "orphanClaimCount": len(orphan_claims),
        "orphanClaims": orphan_claims,
        "knownEvidenceIds": sorted(known_ids),
    }


def _approval_allowance_confirmed(evidence: dict[str, Any]) -> bool:
    if evidence.get("allowanceConfirmed") is not None:
        return bool(evidence.get("allowanceConfirmed"))
    raw_data = evidence.get("rawData") or {}
    if raw_data.get("allowanceConfirmed") is not None:
        return bool(raw_data.get("allowanceConfirmed"))
    endpoint = str(evidence.get("endpoint") or "").lower()
    if "allowance" in endpoint:
        return True
    return any(
        key in raw_data
        for key in ("allowanceRaw", "currentAllowanceRaw", "activeAllowanceRaw")
    )


def _transfer_tx_hash(evidence: dict[str, Any]) -> str | None:
    raw_data = evidence.get("rawData") or {}
    value = raw_data.get("txHash") or raw_data.get("hash") or raw_data.get("transactionHash")
    return str(value) if value else None
