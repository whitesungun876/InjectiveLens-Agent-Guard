from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any


DEFAULT_EXPLORER_BASE_URL = "https://testnet.explorer.injective.network/transaction"
CONFIRMATION = "user_confirmed_record_assessment"


@dataclass
class InMemoryProofStore:
    records: dict[str, dict[str, Any]] = field(default_factory=dict)

    def put(self, proof: dict[str, Any]) -> None:
        self.records[str(proof["assessmentHash"])] = proof

    def get(self, assessment_hash: str) -> dict[str, Any] | None:
        return self.records.get(assessment_hash)

    def load_records(self, records: dict[str, dict[str, Any]]) -> None:
        self.records.update(records)


PROOF_STORE = InMemoryProofStore()


def hydrate_proof_store(records: dict[str, dict[str, Any]]) -> None:
    PROOF_STORE.load_records(records)


def initial_proof_record(mode: str, decision: dict[str, Any], network: str, assessment_hash: str) -> dict[str, Any]:
    if proof_recorder_available() and decision["decision"] in {"allow", "block", "warn"}:
        return {
            "status": "ready_to_record",
            "network": network,
            "txHash": None,
            "explorerUrl": None,
            "proofMethod": "tx_memo",
            "recordedAssessmentHash": None,
            "blockHeight": None,
            "message": "Assessment hash generated. Awaiting explicit proof recording on Injective testnet. This verifies the guard assessment record, not execution safety, trade outcome, or wallet profitability.",
        }
    return unavailable_proof_record(network, "Proof recorder is unavailable or this assessment is not recordable.")


def proof_recorder_available() -> bool:
    mode = os.getenv("INJECTIVE_PROOF_RECORDER_MODE", "external_tx").strip().lower()
    return mode not in {"", "disabled", "off", "false"}


def record_assessment_proof(payload: dict[str, Any], latest_assessment: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    assessment_hash = str(payload.get("assessmentHash") or "")
    network = str(payload.get("network") or "injective_testnet")
    confirmation = str(payload.get("confirmation") or "")
    if confirmation != CONFIRMATION:
        return (
            {
                "error": "confirmation_required",
                "message": "Recording requires explicit confirmation: user_confirmed_record_assessment.",
                "retryable": False,
            },
            400,
        )
    if not assessment_hash.startswith("0x"):
        return ({"error": "bad_request", "message": "assessmentHash is required.", "retryable": False}, 400)
    if latest_assessment and latest_assessment.get("assessmentHash") != assessment_hash:
        return (
            {
                "status": "verified_mismatch",
                "network": network,
                "localAssessmentHash": assessment_hash,
                "onchainAssessmentHash": latest_assessment.get("assessmentHash"),
                "txHash": None,
                "explorerUrl": None,
                "blockHeight": None,
                "message": "Refusing to record: assessment hash does not match the latest pre-flight assessment.",
            },
            409,
        )
    if not proof_recorder_available():
        return (unavailable_proof_record(network, "No Injective proof recorder is configured."), 503)

    tx_hash = _configured_proof_tx_hash()
    if not tx_hash:
        proof = {
            "status": "pending",
            "assessmentId": payload.get("assessmentId") or (latest_assessment or {}).get("assessmentId"),
            "assessmentHash": assessment_hash,
            "network": network,
            "txHash": None,
            "explorerUrl": None,
            "proofMethod": "tx_memo",
            "recordedAssessmentHash": assessment_hash,
            "blockHeight": None,
            "idempotencyKey": payload.get("idempotencyKey") or _hash_payload(payload)[:18],
            "message": "Assessment hash generated. Set INJECTIVE_PROOF_TX_HASH after broadcasting the assessment memo transaction to verify on-chain. This verifies the guard assessment record, not execution safety, trade outcome, or wallet profitability.",
        }
        PROOF_STORE.put(proof)
        return (proof, 202)

    proof = {
        "status": "recorded",
        "assessmentId": payload.get("assessmentId") or (latest_assessment or {}).get("assessmentId"),
        "assessmentHash": assessment_hash,
        "network": network,
        "txHash": tx_hash,
        "explorerUrl": _proof_explorer_url(tx_hash),
        "proofMethod": "tx_memo",
        "recordedAssessmentHash": assessment_hash,
        "blockHeight": _configured_block_height(),
        "idempotencyKey": payload.get("idempotencyKey") or _hash_payload(payload)[:18],
        "message": "Assessment hash recorded on Injective testnet after explicit confirmation. This verifies the guard assessment record, not execution safety, trade outcome, or wallet profitability.",
    }
    PROOF_STORE.put(proof)
    return (proof, 202)


def verify_assessment_proof(payload: dict[str, Any], latest_assessment: dict[str, Any] | None = None) -> dict[str, Any]:
    assessment_hash = str(payload.get("assessmentHash") or "")
    network = str(payload.get("network") or "injective_testnet")
    tx_hash = payload.get("txHash")
    record = PROOF_STORE.get(assessment_hash)
    latest_proof = (latest_assessment or {}).get("proof", {})
    if (
        record is None
        and latest_assessment
        and latest_proof.get("status") in {"recorded", "verified_matched"}
        and latest_proof.get("recordedAssessmentHash") == assessment_hash
    ):
        record = {
            "assessmentHash": assessment_hash,
            "recordedAssessmentHash": assessment_hash,
            "txHash": latest_proof.get("txHash"),
            "explorerUrl": latest_proof.get("explorerUrl"),
            "blockHeight": latest_proof.get("blockHeight"),
        }
    if record is None:
        return {
            "status": "not_found",
            "network": network,
            "localAssessmentHash": assessment_hash,
            "onchainAssessmentHash": None,
            "txHash": tx_hash,
            "explorerUrl": None,
            "blockHeight": None,
            "message": "No recorded proof was found for this assessment hash.",
        }
    if not record.get("txHash"):
        return {
            "status": "not_found",
            "network": network,
            "localAssessmentHash": assessment_hash,
            "onchainAssessmentHash": record.get("recordedAssessmentHash"),
            "txHash": tx_hash,
            "explorerUrl": None,
            "blockHeight": None,
            "message": "Assessment proof is pending; no Injective testnet tx hash has been configured yet.",
        }
    recorded_hash = str(record.get("recordedAssessmentHash") or "")
    matched = bool(assessment_hash) and recorded_hash == assessment_hash
    status = "verified_matched" if matched else "verified_mismatch"
    verified = {
        "status": status,
        "network": network,
        "localAssessmentHash": assessment_hash,
        "onchainAssessmentHash": recorded_hash,
        "txHash": tx_hash or record.get("txHash"),
        "explorerUrl": record.get("explorerUrl"),
        "blockHeight": record.get("blockHeight"),
            "message": "Assessment hash matched the recorded proof. This verifies the guard assessment record, not execution safety, trade outcome, or wallet profitability." if matched else "Local hash does not match recorded proof.",
    }
    if matched:
        PROOF_STORE.put({**record, "status": status})
    return verified


def unavailable_proof_record(network: str, message: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "network": network,
        "txHash": None,
        "explorerUrl": None,
        "proofMethod": "tx_memo",
        "recordedAssessmentHash": None,
        "blockHeight": None,
        "message": message,
    }


def _configured_proof_tx_hash() -> str | None:
    tx_hash = (
        os.getenv("INJECTIVE_PROOF_TX_HASH")
        or os.getenv("INJECTIVE_TESTNET_PROOF_TX_HASH")
        or ""
    ).strip()
    return tx_hash or None


def _configured_block_height() -> int | None:
    raw = (os.getenv("INJECTIVE_PROOF_BLOCK_HEIGHT") or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _proof_explorer_url(tx_hash: str) -> str:
    explicit = (os.getenv("INJECTIVE_PROOF_EXPLORER_URL") or "").strip()
    if explicit:
        return explicit
    base = (os.getenv("INJECTIVE_EXPLORER_TX_BASE_URL") or DEFAULT_EXPLORER_BASE_URL).rstrip("/")
    return f"{base}/{tx_hash}"


def _hash_payload(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
