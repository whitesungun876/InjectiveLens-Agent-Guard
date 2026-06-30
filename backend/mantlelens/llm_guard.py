from __future__ import annotations

from typing import Any

from .explain import rule_based_explanation


FORBIDDEN_PHRASES = (
    "guaranteed wallet safety",
    "production-grade security rating",
    "all risks detected",
    "complete wallet scan",
    "real revoke executed",
    "real swap executed",
    "clean goplus result means safe",
    "meth is rwa",
)


def validate_llm_claims(
    candidate: dict[str, Any],
    assessment: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate a model-like explanation against structured evidence.

    Day 7 uses this guard with deterministic test candidates. A later real LLM
    integration can keep the same contract.
    """

    known_evidence_ids = {item["evidenceId"] for item in evidence}
    allowed_claim_texts = {risk["claimText"] for risk in assessment.get("topRisks", [])}
    failures: list[str] = []

    explanation_text = str(candidate.get("explanation", "")).lower()
    for phrase in FORBIDDEN_PHRASES:
        if phrase in explanation_text:
            failures.append(f"forbidden phrase: {phrase}")

    for claim in candidate.get("claims", []):
        claim_text = claim.get("claimText")
        evidence_ids = claim.get("evidenceIds") or []
        if claim_text not in allowed_claim_texts:
            failures.append(f"unsupported claim: {claim_text}")
        if not evidence_ids:
            failures.append(f"claim has no evidence ids: {claim_text}")
        missing = [evidence_id for evidence_id in evidence_ids if evidence_id not in known_evidence_ids]
        if missing:
            failures.append(f"missing evidence ids for {claim_text}: {', '.join(missing)}")

    return {
        "passed": not failures,
        "failures": failures,
    }


def guarded_explanation(
    candidate: dict[str, Any] | None,
    assessment: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    if candidate is None:
        return rule_based_explanation(
            assessment,
            evidence,
            fallback_reason="No LLM candidate supplied",
        )

    guard = validate_llm_claims(candidate, assessment, evidence)
    if guard["passed"]:
        accepted = dict(candidate)
        accepted["claimGuardPassed"] = True
        accepted["guardFailures"] = []
        accepted.setdefault("mode", "llm_guarded")
        return accepted

    fallback = rule_based_explanation(
        assessment,
        evidence,
        fallback_reason="LLM claim guard failed",
    )
    fallback["claimGuardPassed"] = True
    fallback["guardFailures"] = guard["failures"]
    return fallback
