from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Lock
from typing import Any

from .onchain import AssessmentRecorder


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class InMemoryLedger:
    records: dict[str, dict[str, Any]] = field(default_factory=dict)
    idempotency: dict[str, str] = field(default_factory=dict)
    lock: Lock = field(default_factory=Lock)
    recorder: AssessmentRecorder | None = None

    def commit_assessment(
        self,
        assessment: dict[str, Any],
        *,
        idempotency_key: str,
        trace_id: str,
        simulation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self.lock:
            if idempotency_key in self.idempotency:
                record_id = self.idempotency[idempotency_key]
                return dict(self.records[record_id])

            assessment_id = assessment["assessmentId"]
            record_id = f"{assessment_id}:{idempotency_key}"
            assessment_uri = f"memory://assessments/{assessment_id}"
            onchain_record = (self.recorder or AssessmentRecorder.from_env()).record_assessment(
                assessment,
                assessment_uri=assessment_uri,
                trace_id=trace_id,
            )
            chain_id = int(onchain_record.get("chainId") or assessment.get("chainId") or 5000)
            record = {
                "recordId": record_id,
                "assessmentId": assessment_id,
                "agentId": "mantlelens-wallet-guard-demo",
                "walletHash": assessment["wallet"]["walletHash"],
                "walletRiskScore": assessment["walletRiskScore"],
                "riskLevel": assessment["riskLevel"],
                "dataConfidence": assessment["dataConfidence"],
                "topRisksHash": assessment["topRisksHash"],
                "evidenceBundleHash": assessment["evidenceBundleHash"],
                "recommendationHash": assessment["recommendationHash"],
                "simulationOutcomeHash": simulation.get("simulationHash") if simulation else None,
                "dataMode": assessment["dataMode"],
                "chainId": chain_id,
                "networkName": onchain_record.get("networkName") or _network_name(chain_id),
                "decisionType": assessment["decisionType"],
                "actionType": assessment["actionType"],
                "assessmentURI": assessment_uri,
                "assessmentHash": assessment["assessmentHash"],
                "assessmentTx": onchain_record["assessmentTx"],
                "explorerUrl": onchain_record.get("explorerUrl"),
                "commitMode": onchain_record["commitMode"],
                "onchainRecordAvailable": onchain_record["onchainRecordAvailable"],
                "onchainWriteAttempted": onchain_record["onchainWriteAttempted"],
                "unavailableReason": onchain_record.get("unavailableReason"),
                "retryReason": onchain_record.get("retryReason"),
                "contractAddress": onchain_record.get("contractAddress"),
                "signerAddress": onchain_record.get("signerAddress"),
                "outcomeHash": None,
                "outcomeTx": None,
                "userResponse": "simulated" if simulation else "viewed",
                "outcomeStatus": "pending",
                "status": onchain_record["status"],
                "idempotencyKey": idempotency_key,
                "traceId": trace_id,
                "recordedAt": _now(),
                "realExecutionAllowed": False,
            }
            self.records[record_id] = record
            self.idempotency[idempotency_key] = record_id
            return dict(record)

    def history(self, wallet_hash: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        with self.lock:
            records = list(self.records.values())
        if wallet_hash:
            records = [record for record in records if record["walletHash"] == wallet_hash]
        records.sort(key=lambda record: record["recordedAt"], reverse=True)
        return [dict(record) for record in records[:limit]]

    def record_outcome(
        self,
        *,
        assessment_id: str,
        outcome_hash: str,
        user_response: str,
        idempotency_key: str,
        trace_id: str,
    ) -> dict[str, Any]:
        with self.lock:
            match = None
            for record in self.records.values():
                if record["assessmentId"] == assessment_id:
                    match = record
                    break
            if match is None:
                match = {
                    "recordId": f"{assessment_id}:outcome:{idempotency_key}",
                    "assessmentId": assessment_id,
                    "agentId": "mantlelens-wallet-guard-demo",
                    "walletHash": None,
                    "walletRiskScore": None,
                    "riskLevel": None,
                    "dataConfidence": None,
                    "topRisksHash": None,
                    "evidenceBundleHash": None,
                    "recommendationHash": None,
                    "simulationOutcomeHash": None,
                    "dataMode": "unknown",
                    "chainId": None,
                    "networkName": None,
                    "decisionType": None,
                    "actionType": None,
                    "assessmentURI": f"memory://assessments/{assessment_id}",
                    "assessmentHash": None,
                    "assessmentTx": None,
                    "explorerUrl": None,
                    "commitMode": "local_outcome_only",
                    "onchainRecordAvailable": False,
                    "onchainWriteAttempted": False,
                    "unavailableReason": "assessment commit record was not found",
                    "retryReason": None,
                    "contractAddress": None,
                    "signerAddress": None,
                    "status": "pending_unavailable",
                    "idempotencyKey": idempotency_key,
                    "traceId": trace_id,
                    "recordedAt": _now(),
                    "realExecutionAllowed": False,
                }
                self.records[match["recordId"]] = match

            match["outcomeHash"] = outcome_hash
            match["outcomeTx"] = None
            match["userResponse"] = user_response
            match["outcomeStatus"] = "recorded"
            match["outcomeRecordedAt"] = _now()
            match["realExecutionAllowed"] = False
            return dict(match)


LEDGER = InMemoryLedger()


def _network_name(chain_id: int) -> str:
    if chain_id == 5003:
        return "Mantle Sepolia"
    if chain_id == 5000:
        return "Mantle Mainnet"
    return f"Mantle Chain {chain_id}"
