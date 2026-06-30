from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

from .hashutil import stable_hash


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class InMemoryAlertStore:
    _open_by_key: dict[str, dict[str, Any]] = field(default_factory=dict)
    _resolved_by_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def evaluate(
        self,
        *,
        assessment: dict[str, Any],
        evidence_bundle: dict[str, Any],
        coverage: dict[str, Any],
        inventory: dict[str, Any] | None,
        history: dict[str, Any] | None,
        trend: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        candidates = build_alert_candidates(
            assessment=assessment,
            evidence_bundle=evidence_bundle,
            coverage=coverage,
            inventory=inventory,
            history=history,
            trend=trend,
        )
        with self._lock:
            alerts = [self._open_or_update(candidate) for candidate in candidates]
        return alerts

    def reset(self) -> None:
        with self._lock:
            self._open_by_key.clear()
            self._resolved_by_id.clear()

    def list_alerts(
        self,
        *,
        wallet_hash: str | None = None,
        wallet_address: str | None = None,
        chain_id: int | None = None,
        mode: str | None = None,
        status: str = "open",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with self._lock:
            if status == "resolved":
                alerts = list(self._resolved_by_id.values())
            elif status == "all":
                alerts = list(self._open_by_key.values()) + list(self._resolved_by_id.values())
            else:
                alerts = list(self._open_by_key.values())
        if wallet_hash:
            alerts = [alert for alert in alerts if alert.get("walletHash") == wallet_hash]
        if wallet_address:
            alerts = [alert for alert in alerts if alert.get("walletAddress") == _normalize_address(wallet_address)]
        if chain_id is not None:
            alerts = [alert for alert in alerts if int(alert.get("chainId") or 0) == int(chain_id)]
        if mode:
            alerts = [alert for alert in alerts if alert.get("mode") == mode]
        alerts.sort(key=lambda item: item.get("createdAt") or "", reverse=True)
        return [dict(alert) for alert in alerts[:limit]]

    def resolve(
        self,
        *,
        alert_id: str,
        resolution_note: str | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            match_key = None
            match = None
            for dedupe_key, alert in self._open_by_key.items():
                if alert.get("alertId") == alert_id:
                    match_key = dedupe_key
                    match = alert
                    break
            if match is None or match_key is None:
                resolved = self._resolved_by_id.get(alert_id)
                return dict(resolved) if resolved else None
            alert = dict(match)
            alert["status"] = "resolved"
            alert["resolvedAt"] = _now()
            alert["resolutionNote"] = resolution_note or "Resolved locally"
            self._open_by_key.pop(match_key, None)
            self._resolved_by_id[alert_id] = alert
            return dict(alert)

    def _open_or_update(self, candidate: dict[str, Any]) -> dict[str, Any]:
        dedupe_key = candidate["dedupeKey"]
        existing = self._open_by_key.get(dedupe_key)
        if existing is not None:
            existing["lastSeenAt"] = _now()
            existing["last_seen_at"] = existing["lastSeenAt"]
            existing["lastSeenAssessmentHash"] = candidate["sourceAssessmentHash"]
            existing["occurrenceCount"] += 1
            return dict(existing)

        alert_id = f"alert_{stable_hash(dedupe_key)[2:18]}"
        alert = {
            "alertId": alert_id,
            "alert_id": alert_id,
            "status": "open",
            "createdAt": _now(),
            "created_at": _now(),
            "resolvedAt": None,
            "resolved_at": None,
            "lastSeenAt": None,
            "last_seen_at": None,
            "lastSeenAssessmentHash": None,
            "occurrenceCount": 1,
            **candidate,
        }
        alert = _with_alert_aliases(alert)
        self._open_by_key[dedupe_key] = alert
        return dict(alert)


class SQLiteAlertStore:
    """Durable alert store with the same API as the in-memory store."""

    def __init__(self, db_path: str | os.PathLike[str]) -> None:
        self.db_path = str(db_path)
        self._lock = Lock()
        self._ensure_schema()

    def evaluate(
        self,
        *,
        assessment: dict[str, Any],
        evidence_bundle: dict[str, Any],
        coverage: dict[str, Any],
        inventory: dict[str, Any] | None,
        history: dict[str, Any] | None,
        trend: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        candidates = build_alert_candidates(
            assessment=assessment,
            evidence_bundle=evidence_bundle,
            coverage=coverage,
            inventory=inventory,
            history=history,
            trend=trend,
        )
        with self._lock:
            return [self._open_or_update(candidate) for candidate in candidates]

    def reset(self) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM alerts")

    def list_alerts(
        self,
        *,
        wallet_hash: str | None = None,
        wallet_address: str | None = None,
        chain_id: int | None = None,
        mode: str | None = None,
        status: str = "open",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        where = []
        params: list[Any] = []
        if status != "all":
            where.append("status = ?")
            params.append(status)
        if wallet_hash:
            where.append("wallet_hash = ?")
            params.append(wallet_hash)
        query = "SELECT alert_json FROM alerts"
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        alerts = [json.loads(row[0]) for row in rows]
        if wallet_address:
            alerts = [alert for alert in alerts if alert.get("walletAddress") == _normalize_address(wallet_address)]
        if chain_id is not None:
            alerts = [alert for alert in alerts if int(alert.get("chainId") or 0) == int(chain_id)]
        if mode:
            alerts = [alert for alert in alerts if alert.get("mode") == mode]
        return alerts[:limit]

    def resolve(
        self,
        *,
        alert_id: str,
        resolution_note: str | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT alert_json FROM alerts WHERE alert_id = ?",
                    (alert_id,),
                ).fetchone()
                if row is None:
                    return None
                alert = json.loads(row[0])
                if alert.get("status") == "resolved":
                    return alert
                alert["status"] = "resolved"
                alert["resolvedAt"] = _now()
                alert["resolved_at"] = alert["resolvedAt"]
                alert["resolutionNote"] = resolution_note or "Resolved locally"
                alert["resolution_note"] = alert["resolutionNote"]
                conn.execute(
                    """
                    UPDATE alerts
                    SET status = ?, resolved_at = ?, alert_json = ?
                    WHERE alert_id = ?
                    """,
                    (
                        "resolved",
                        alert["resolvedAt"],
                        json.dumps(alert, sort_keys=True),
                        alert_id,
                    ),
                )
                return alert

    def _open_or_update(self, candidate: dict[str, Any]) -> dict[str, Any]:
        dedupe_key = candidate["dedupeKey"]
        with self._connect() as conn:
            row = conn.execute(
                "SELECT alert_json FROM alerts WHERE dedupe_key = ? AND status = 'open'",
                (dedupe_key,),
            ).fetchone()
            if row is not None:
                existing = json.loads(row[0])
                existing["lastSeenAt"] = _now()
                existing["last_seen_at"] = existing["lastSeenAt"]
                existing["lastSeenAssessmentHash"] = candidate["sourceAssessmentHash"]
                existing["occurrenceCount"] += 1
                conn.execute(
                    """
                    UPDATE alerts
                    SET last_seen_at = ?, source_assessment_hash = ?, alert_json = ?
                    WHERE alert_id = ?
                    """,
                    (
                        existing["lastSeenAt"],
                        existing["lastSeenAssessmentHash"],
                        json.dumps(existing, sort_keys=True),
                        existing["alertId"],
                    ),
                )
                return existing

            alert_id = f"alert_{stable_hash(dedupe_key)[2:18]}"
            alert = {
                "alertId": alert_id,
                "alert_id": alert_id,
                "status": "open",
                "createdAt": _now(),
                "created_at": _now(),
                "resolvedAt": None,
                "resolved_at": None,
                "lastSeenAt": None,
                "last_seen_at": None,
                "lastSeenAssessmentHash": None,
                "occurrenceCount": 1,
                **candidate,
            }
            alert = _with_alert_aliases(alert)
            conn.execute(
                """
                INSERT OR REPLACE INTO alerts (
                    alert_id,
                    dedupe_key,
                    wallet_hash,
                    status,
                    created_at,
                    resolved_at,
                    source_assessment_hash,
                    last_seen_at,
                    alert_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert["alertId"],
                    dedupe_key,
                    alert["walletHash"],
                    alert["status"],
                    alert["createdAt"],
                    alert["resolvedAt"],
                    alert["sourceAssessmentHash"],
                    alert["lastSeenAt"],
                    json.dumps(alert, sort_keys=True),
                ),
            )
            return alert

    def _connect(self) -> sqlite3.Connection:
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(self.db_path)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS alerts (
                    alert_id TEXT PRIMARY KEY,
                    dedupe_key TEXT NOT NULL,
                    wallet_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    source_assessment_hash TEXT NOT NULL,
                    last_seen_at TEXT,
                    alert_json TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_wallet_status ON alerts(wallet_hash, status, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_dedupe_status ON alerts(dedupe_key, status)")


def build_alert_candidates(
    *,
    assessment: dict[str, Any],
    evidence_bundle: dict[str, Any],
    coverage: dict[str, Any],
    inventory: dict[str, Any] | None,
    history: dict[str, Any] | None,
    trend: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    wallet_hash = assessment["wallet"]["walletHash"]
    assessment_hash = assessment["assessmentHash"]
    evidence_by_id = {
        item.get("evidenceId"): item
        for item in evidence_bundle.get("evidence", [])
        if item.get("evidenceId")
    }
    candidates: list[dict[str, Any]] = []

    for risk in assessment.get("topRisks", []):
        risk_type = risk.get("type")
        if risk_type == "approval":
            candidates.append(
                _candidate(
                    assessment=assessment,
                    alert_type="new_active_approval",
                    severity=_alert_severity(risk.get("severity")),
                    title="New active approval detected",
                    message=risk.get("claimText") or "An active token approval requires review.",
                    evidence_ids=_valid_evidence_ids(risk.get("evidenceIds", []), evidence_by_id),
                    dedupe_parts=[wallet_hash, "approval", risk.get("riskId"), risk.get("evidenceIds", [])],
                )
            )
        elif risk_type == "transfer":
            candidates.append(
                _candidate(
                    assessment=assessment,
                    alert_type="suspicious_transfer_detected",
                    severity=_alert_severity(risk.get("severity")),
                    title="Suspicious transfer pattern detected",
                    message=risk.get("claimText") or "A suspicious transfer pattern requires review.",
                    evidence_ids=_valid_evidence_ids(risk.get("evidenceIds", []), evidence_by_id),
                    dedupe_parts=[wallet_hash, "transfer", risk.get("riskId"), risk.get("evidenceIds", [])],
                )
            )

    candidates.extend(_trend_candidates(assessment, trend))
    candidates.extend(_token_security_candidates(assessment, inventory, history, evidence_by_id))
    candidates.extend(_source_unavailable_candidates(assessment, coverage))
    return [candidate for candidate in candidates if _is_bound(candidate)]


def _trend_candidates(
    assessment: dict[str, Any],
    trend: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not trend or not trend.get("delta"):
        return _source_coverage_degradation_candidates(assessment, trend)
    wallet_hash = assessment["wallet"]["walletHash"]
    delta = trend["delta"]
    candidates = []
    score_delta = float(delta.get("scoreDelta") or 0)
    if score_delta > 0:
        candidates.append(
            _candidate(
                assessment=assessment,
                alert_type="risk_score_increased",
                severity="High" if score_delta >= 20 else "Moderate",
                title="Risk score increased",
                message=f"Wallet risk score increased by {score_delta:g} points since the previous assessment.",
                evidence_ids=[],
                dedupe_parts=[wallet_hash, "score_increased", delta.get("previousAssessmentHash"), delta.get("currentAssessmentHash")],
                related_assessment_hashes=[
                    delta.get("previousAssessmentHash"),
                    delta.get("currentAssessmentHash"),
                ],
            )
        )

    if delta.get("riskLevelChanged") and _severity_rank(delta.get("currentRiskLevel")) > _severity_rank(delta.get("previousRiskLevel")):
        candidates.append(
            _candidate(
                assessment=assessment,
                alert_type="risk_level_increased",
                severity=_alert_severity(delta.get("currentRiskLevel")),
                title="Risk level increased",
                message=f"Risk level changed from {delta.get('previousRiskLevel')} to {delta.get('currentRiskLevel')}.",
                evidence_ids=[],
                dedupe_parts=[wallet_hash, "level_increased", delta.get("previousAssessmentHash"), delta.get("currentAssessmentHash")],
                related_assessment_hashes=[
                    delta.get("previousAssessmentHash"),
                    delta.get("currentAssessmentHash"),
                ],
            )
        )
    candidates.extend(_source_coverage_degradation_candidates(assessment, trend))
    return candidates


def _source_coverage_degradation_candidates(
    assessment: dict[str, Any],
    trend: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not trend:
        return []
    wallet_hash = assessment["wallet"]["walletHash"]
    candidates = []
    for change in trend.get("sourceCoverageChanges") or []:
        if not isinstance(change, dict) or change.get("direction") != "degraded":
            continue
        source = change.get("source") or "unknown_source"
        candidates.append(
            _candidate(
                assessment=assessment,
                alert_type="source_coverage_degraded",
                severity="Moderate",
                title="Source coverage degraded",
                message=f"{source} changed from {change.get('previous')} to {change.get('current')}; trend improvement is not confirmed.",
                evidence_ids=[],
                dedupe_parts=[wallet_hash, "source_coverage_degraded", source],
                source_status=str(change.get("current") or "unknown"),
            )
        )
    return candidates


def _token_security_candidates(
    assessment: dict[str, Any],
    inventory: dict[str, Any] | None,
    history: dict[str, Any] | None,
    evidence_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    tokens: list[dict[str, Any]] = []
    if isinstance(inventory, dict):
        tokens.extend(item for item in inventory.get("tokens", []) if isinstance(item, dict))
    if isinstance(history, dict):
        security_rows = history.get("tokenSecurity") or []
        if isinstance(security_rows, list):
            tokens.extend(item for item in security_rows if isinstance(item, dict))

    candidates = []
    wallet_hash = assessment["wallet"]["walletHash"]
    seen: set[str] = set()
    for token in tokens:
        status = token.get("securityStatus") or token.get("status")
        if status != "risky":
            continue
        token_address = str(token.get("tokenAddress") or token.get("address") or "unknown").lower()
        if token_address in seen:
            continue
        seen.add(token_address)
        evidence_ids = _valid_evidence_ids(token.get("evidenceIds") or [token.get("evidenceId")], evidence_by_id)
        candidates.append(
            _candidate(
                assessment=assessment,
                alert_type="token_security_risky",
                severity="High",
                title="Risky token security signal",
                message=f"{token.get('symbol') or token_address} has a risky token security signal.",
                evidence_ids=evidence_ids,
                dedupe_parts=[wallet_hash, "token_security", token_address, evidence_ids],
            )
        )
    return candidates


def _source_unavailable_candidates(
    assessment: dict[str, Any],
    coverage: dict[str, Any],
) -> list[dict[str, Any]]:
    wallet_hash = assessment["wallet"]["walletHash"]
    candidates = []
    data_completeness = coverage.get("dataCompleteness", {})
    for name, status in sorted(data_completeness.items()):
        if status not in {"unavailable", "not_supported_p0", "source_failed"}:
            continue
        candidates.append(
            _candidate(
                assessment=assessment,
                alert_type="source_unavailable",
                severity="Moderate",
                title="Wallet data source unavailable",
                message=f"{name} is unavailable, so missing data remains unknown.",
                evidence_ids=[],
                dedupe_parts=[wallet_hash, "data_completeness", name],
                source_status=status,
            )
        )

    source_availability = coverage.get("sourceAvailability", {})
    for name, source in sorted(source_availability.items()):
        if not isinstance(source, dict) or source.get("status") != "unavailable":
            continue
            candidates.append(
                _candidate(
                assessment=assessment,
                alert_type="source_unavailable",
                severity="Moderate",
                title="External source unavailable",
                message=f"{name} is unavailable: {source.get('limitation') or 'source missing'}.",
                    evidence_ids=[],
                    dedupe_parts=[wallet_hash, "source", name],
                    source_status=str(source.get("status") or "unknown"),
                )
            )
    return candidates


def _candidate(
    *,
    assessment: dict[str, Any],
    alert_type: str,
    severity: str,
    title: str,
    message: str,
    evidence_ids: list[str],
    dedupe_parts: list[Any],
    related_assessment_hashes: list[str | None] | None = None,
    source_status: str | None = None,
    related_tx_hash: str | None = None,
) -> dict[str, Any]:
    wallet = assessment.get("wallet", {})
    wallet_address = _normalize_address(wallet.get("address"))
    chain_id = int(assessment.get("chainId") or 5000)
    actions = _recommended_safe_actions(alert_type)
    dedupe_key = stable_hash(dedupe_parts)
    return {
        "walletHash": wallet["walletHash"],
        "wallet_hash": wallet["walletHash"],
        "walletAddress": wallet_address,
        "wallet_address": wallet_address,
        "chainId": chain_id,
        "chain_id": chain_id,
        "networkName": _network_name(chain_id),
        "network_name": _network_name(chain_id),
        "mode": assessment.get("dataMode") or "demo",
        "assessmentId": assessment["assessmentId"],
        "relatedAssessmentId": assessment["assessmentId"],
        "related_assessment_id": assessment["assessmentId"],
        "alertType": alert_type,
        "type": alert_type,
        "severity": severity,
        "title": title,
        "message": message,
        "description": message,
        "evidenceIds": evidence_ids,
        "evidence_ids": evidence_ids,
        "sourceAssessmentHash": assessment["assessmentHash"],
        "relatedAssessmentHashes": [item for item in (related_assessment_hashes or []) if item],
        "relatedTxHash": related_tx_hash,
        "related_tx_hash": related_tx_hash,
        "sourceStatus": source_status or assessment.get("dataStatus") or "unknown",
        "source_status": source_status or assessment.get("dataStatus") or "unknown",
        "recommendedSafeActions": actions,
        "recommended_safe_actions": actions,
        "dedupeKey": dedupe_key,
        "dedup_key": dedupe_key,
    }


def _valid_evidence_ids(
    ids: Any,
    evidence_by_id: dict[str, dict[str, Any]],
) -> list[str]:
    if not isinstance(ids, list):
        ids = [ids]
    valid = [item for item in ids if item and item in evidence_by_id]
    return list(dict.fromkeys(valid))


def _is_bound(candidate: dict[str, Any]) -> bool:
    return bool(
        candidate.get("evidenceIds")
        or candidate.get("sourceAssessmentHash")
        or candidate.get("relatedAssessmentHashes")
    )


def _alert_severity(value: Any) -> str:
    text = str(value or "Moderate")
    if text in {"Critical", "High", "Moderate", "Low"}:
        return text
    return "Moderate"


def _severity_rank(value: Any) -> int:
    return {"Low": 1, "Moderate": 2, "High": 3, "Critical": 4}.get(str(value), 0)


def _recommended_safe_actions(alert_type: str) -> list[str]:
    actions = {
        "new_active_approval": ["review spender", "simulate revoke impact"],
        "suspicious_transfer_detected": ["mark counterparty suspicious", "review transfer log"],
        "risk_score_increased": ["review top risks", "inspect evidence"],
        "risk_level_increased": ["review top risks", "inspect evidence"],
        "source_coverage_degraded": ["check source coverage", "rescan later"],
        "source_unavailable": ["check source coverage", "rescan later"],
        "token_security_risky": ["inspect token", "check source coverage"],
        "commit_failed": ["verify on-chain record", "retry manually later"],
    }
    return actions.get(alert_type, ["review evidence"])


def _with_alert_aliases(alert: dict[str, Any]) -> dict[str, Any]:
    alert["alert_id"] = alert.get("alert_id") or alert.get("alertId")
    alert["created_at"] = alert.get("created_at") or alert.get("createdAt")
    alert["resolved_at"] = alert.get("resolved_at") if "resolved_at" in alert else alert.get("resolvedAt")
    alert["last_seen_at"] = alert.get("last_seen_at") if "last_seen_at" in alert else alert.get("lastSeenAt")
    alert["wallet_address"] = alert.get("wallet_address") if "wallet_address" in alert else alert.get("walletAddress")
    alert["chain_id"] = alert.get("chain_id") if "chain_id" in alert else alert.get("chainId")
    alert["network_name"] = alert.get("network_name") if "network_name" in alert else alert.get("networkName")
    alert["evidence_ids"] = alert.get("evidence_ids") or alert.get("evidenceIds") or []
    alert["dedup_key"] = alert.get("dedup_key") or alert.get("dedupeKey")
    alert["resolution_note"] = alert.get("resolution_note") if "resolution_note" in alert else alert.get("resolutionNote")
    return alert


def _normalize_address(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    return text.lower() if text.startswith("0x") else text


def _network_name(chain_id: int) -> str:
    if chain_id == 5003:
        return "Mantle Sepolia"
    if chain_id == 5000:
        return "Mantle Mainnet"
    return f"Mantle Chain {chain_id}"


def _state_db_path() -> str:
    return os.getenv("MANTLELENS_STATE_DB", "data/mantlelens.sqlite3")


def _use_memory_store() -> bool:
    return os.getenv("MANTLELENS_DISABLE_PERSISTENCE", "").strip().lower() in {"1", "true", "yes", "on"}


ALERT_STORE = InMemoryAlertStore() if _use_memory_store() else SQLiteAlertStore(_state_db_path())
