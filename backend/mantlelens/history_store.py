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


SOURCE_ORDER = {"available": 4, "partial": 3, "unknown": 2, "unavailable": 1, "source_failed": 0}
LEVEL_ORDER = {"Low": 1, "Moderate": 2, "Medium": 2, "High": 3, "Critical": 4}
COMPARABILITY_STATUSES = {"comparable", "partially_comparable", "not_comparable", "insufficient_history"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class InMemoryAssessmentHistoryStore:
    max_records_per_wallet: int = 100
    _records: list[dict[str, Any]] = field(default_factory=list)
    _lock: Lock = field(default_factory=Lock)

    def record_scan(
        self,
        *,
        assessment: dict[str, Any],
        evidence_bundle: dict[str, Any],
        coverage: dict[str, Any],
        inventory: dict[str, Any] | None,
        history: dict[str, Any] | None,
        commit_record: dict[str, Any] | None = None,
        commit_verification: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = assessment_history_record(
            assessment=assessment,
            evidence_bundle=evidence_bundle,
            coverage=coverage,
            inventory=inventory,
            history=history,
            commit_record=commit_record,
            commit_verification=commit_verification,
        )
        with self._lock:
            self._records.append(record)
            matching = [
                item
                for item in self._records
                if _same_wallet_key(item, record["walletAddress"], record["chainId"], record["mode"])
            ]
            if len(matching) > self.max_records_per_wallet:
                remove_ids = {item["historyRecordId"] for item in matching[: len(matching) - self.max_records_per_wallet]}
                self._records = [item for item in self._records if item["historyRecordId"] not in remove_ids]
        return dict(record)

    def list_records(
        self,
        *,
        address: str | None = None,
        wallet_hash: str | None = None,
        chain_id: int | None = None,
        mode: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        with self._lock:
            records = [dict(item) for item in self._records]
        records = _filter_records(records, address=address, wallet_hash=wallet_hash, chain_id=chain_id, mode=mode)
        records.sort(key=lambda item: (item.get("scanTimestamp") or "", item.get("createdAt") or ""), reverse=True)
        return records[:limit]

    def attach_commit(self, commit_record: dict[str, Any]) -> dict[str, Any] | None:
        patch = _commit_record_patch(commit_record)
        return self._patch_matching_record(commit_record, patch)

    def attach_commit_verification(self, verification: dict[str, Any]) -> dict[str, Any] | None:
        patch = _commit_verification_patch(verification)
        return self._patch_matching_record(verification, patch)

    def trend(
        self,
        *,
        address: str | None = None,
        wallet_hash: str | None = None,
        chain_id: int | None = None,
        mode: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        records_desc = self.list_records(address=address, wallet_hash=wallet_hash, chain_id=chain_id, mode=mode, limit=limit)
        return build_trend_response(list(reversed(records_desc)), requested_address=address, requested_wallet_hash=wallet_hash, chain_id=chain_id, mode=mode)

    def reset(self) -> None:
        with self._lock:
            self._records.clear()

    def _patch_matching_record(self, source: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any] | None:
        if not patch:
            return None
        updated: dict[str, Any] | None = None
        with self._lock:
            for record in self._records:
                if _matches_assessment_or_commit(record, source):
                    record.update(patch)
                    updated = dict(record)
        return updated


class SQLiteAssessmentHistoryStore:
    def __init__(self, db_path: str | os.PathLike[str], max_records_per_wallet: int = 100) -> None:
        self.db_path = str(db_path)
        self.max_records_per_wallet = max_records_per_wallet
        self._lock = Lock()
        self._ensure_schema()

    def record_scan(
        self,
        *,
        assessment: dict[str, Any],
        evidence_bundle: dict[str, Any],
        coverage: dict[str, Any],
        inventory: dict[str, Any] | None,
        history: dict[str, Any] | None,
        commit_record: dict[str, Any] | None = None,
        commit_verification: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = assessment_history_record(
            assessment=assessment,
            evidence_bundle=evidence_bundle,
            coverage=coverage,
            inventory=inventory,
            history=history,
            commit_record=commit_record,
            commit_verification=commit_verification,
        )
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO assessment_history (
                        history_record_id,
                        wallet_address,
                        wallet_hash,
                        chain_id,
                        network_name,
                        mode,
                        scan_timestamp,
                        risk_score,
                        risk_level,
                        data_status,
                        assessment_hash,
                        record_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["historyRecordId"],
                        record["walletAddress"],
                        record["walletHash"],
                        int(record["chainId"]),
                        record["networkName"],
                        record["mode"],
                        record["scanTimestamp"],
                        float(record["riskScore"]),
                        record["riskLevel"],
                        record["status"],
                        record["assessmentHash"],
                        json.dumps(record, sort_keys=True),
                    ),
                )
                stale = [
                    row[0]
                    for row in conn.execute(
                        """
                        SELECT history_record_id
                        FROM assessment_history
                        WHERE wallet_hash = ? AND chain_id = ? AND mode = ?
                        ORDER BY scan_timestamp DESC, id DESC
                        LIMIT -1 OFFSET ?
                        """,
                        (record["walletHash"], int(record["chainId"]), record["mode"], self.max_records_per_wallet),
                    ).fetchall()
                ]
                if stale:
                    conn.executemany("DELETE FROM assessment_history WHERE history_record_id = ?", [(item,) for item in stale])
        return dict(record)

    def list_records(
        self,
        *,
        address: str | None = None,
        wallet_hash: str | None = None,
        chain_id: int | None = None,
        mode: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        where: list[str] = []
        params: list[Any] = []
        if wallet_hash:
            where.append("wallet_hash = ?")
            params.append(wallet_hash)
        elif address:
            where.append("wallet_address = ?")
            params.append(_normalize_address(address))
        if chain_id is not None:
            where.append("chain_id = ?")
            params.append(int(chain_id))
        if mode:
            where.append("mode = ?")
            params.append(mode)
        query = "SELECT record_json FROM assessment_history"
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY scan_timestamp DESC, id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [json.loads(row[0]) for row in rows]

    def attach_commit(self, commit_record: dict[str, Any]) -> dict[str, Any] | None:
        patch = _commit_record_patch(commit_record)
        return self._patch_matching_record(commit_record, patch)

    def attach_commit_verification(self, verification: dict[str, Any]) -> dict[str, Any] | None:
        patch = _commit_verification_patch(verification)
        return self._patch_matching_record(verification, patch)

    def trend(
        self,
        *,
        address: str | None = None,
        wallet_hash: str | None = None,
        chain_id: int | None = None,
        mode: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        records_desc = self.list_records(address=address, wallet_hash=wallet_hash, chain_id=chain_id, mode=mode, limit=limit)
        return build_trend_response(list(reversed(records_desc)), requested_address=address, requested_wallet_hash=wallet_hash, chain_id=chain_id, mode=mode)

    def reset(self) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM assessment_history")

    def _patch_matching_record(self, source: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any] | None:
        if not patch:
            return None
        updated: dict[str, Any] | None = None
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT id, record_json
                    FROM assessment_history
                    ORDER BY scan_timestamp DESC, id DESC
                    """
                ).fetchall()
                for row_id, record_json in rows:
                    record = json.loads(record_json)
                    if not _matches_assessment_or_commit(record, source):
                        continue
                    record.update(patch)
                    conn.execute(
                        "UPDATE assessment_history SET record_json = ? WHERE id = ?",
                        (json.dumps(record, sort_keys=True), row_id),
                    )
                    if updated is None:
                        updated = dict(record)
        return updated

    def _connect(self) -> sqlite3.Connection:
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(self.db_path)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS assessment_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    history_record_id TEXT NOT NULL UNIQUE,
                    wallet_address TEXT,
                    wallet_hash TEXT NOT NULL,
                    chain_id INTEGER NOT NULL,
                    network_name TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    scan_timestamp TEXT NOT NULL,
                    risk_score REAL NOT NULL,
                    risk_level TEXT NOT NULL,
                    data_status TEXT NOT NULL,
                    assessment_hash TEXT,
                    record_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_assessment_history_wallet
                ON assessment_history(wallet_hash, chain_id, mode, scan_timestamp)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_assessment_history_address
                ON assessment_history(wallet_address, chain_id, mode, scan_timestamp)
                """
            )


def assessment_history_record(
    *,
    assessment: dict[str, Any],
    evidence_bundle: dict[str, Any],
    coverage: dict[str, Any],
    inventory: dict[str, Any] | None,
    history: dict[str, Any] | None,
    commit_record: dict[str, Any] | None = None,
    commit_verification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    wallet = assessment.get("wallet", {})
    chain_id = int(assessment.get("chainId") or 5000)
    source_statuses = coverage.get("sourceAvailability", {})
    source_coverage_summary = _source_coverage_summary(coverage)
    top_risks = [_top_risk_summary(risk) for risk in assessment.get("topRisks", []) if isinstance(risk, dict)]
    evidence_ids = sorted(
        {
            evidence_id
            for risk in top_risks
            for evidence_id in risk.get("evidenceIds", [])
            if isinstance(evidence_id, str)
        }
        | {
            item.get("evidenceId")
            for item in evidence_bundle.get("evidence", [])
            if isinstance(item, dict) and item.get("evidenceId")
        }
    )
    risk_categories = sorted({risk.get("category") or risk.get("type") for risk in assessment.get("topRisks", []) if isinstance(risk, dict) and (risk.get("category") or risk.get("type"))})
    scan_timestamp = assessment.get("timestamp") or _now()
    wallet_address = _normalize_address(wallet.get("address"))
    benchmark_case = assessment.get("benchmarkCase") if isinstance(assessment.get("benchmarkCase"), dict) else {}
    record = {
        "historyRecordId": stable_hash(
            {
                "assessmentHash": assessment.get("assessmentHash"),
                "scanTimestamp": scan_timestamp,
                "walletHash": wallet.get("walletHash"),
            }
        ),
        "assessmentId": assessment.get("assessmentId"),
        "walletAddress": wallet_address,
        "walletHash": wallet.get("walletHash"),
        "chainId": chain_id,
        "networkName": _network_name(chain_id),
        "mode": assessment.get("dataMode") or "demo",
        "fixtureId": assessment.get("fixtureId"),
        "benchmarkCaseId": benchmark_case.get("id"),
        "benchmarkCaseLabel": benchmark_case.get("label"),
        "scanTimestamp": scan_timestamp,
        "riskScore": float(assessment.get("walletRiskScore") or 0),
        "riskLevel": assessment.get("riskLevel"),
        "confidence": float(assessment.get("dataConfidence") or 0),
        "status": _assessment_status(assessment),
        "sourceStatuses": source_statuses,
        "sourceCoverageSummary": source_coverage_summary,
        "topRiskSummaries": top_risks,
        "riskCategories": risk_categories,
        "evidenceIds": evidence_ids,
        "assessmentHash": assessment.get("assessmentHash"),
        "evidenceBundleHash": evidence_bundle.get("evidenceBundleHash") or assessment.get("evidenceBundleHash"),
        "commitTxHash": (commit_record or {}).get("assessmentTx"),
        "commitStatus": (commit_record or {}).get("status"),
        "commitMode": (commit_record or {}).get("commitMode"),
        "commitExplorerUrl": (commit_record or {}).get("explorerUrl") or (commit_verification or {}).get("explorerUrl"),
        "commitVerificationStatus": (commit_verification or {}).get("verificationStatus") or (commit_verification or {}).get("status"),
        "assessmentContractAddress": (commit_record or {}).get("contractAddress") or (commit_verification or {}).get("contractAddress"),
        "createdAt": _now(),
        "recordSource": "mantlelens_assessment_history_v1",
        "detailCounts": {
            "inventoryTokens": len((inventory or {}).get("tokens", []) if isinstance(inventory, dict) else []),
            "approvals": len(((history or {}).get("approvalHistory") or {}).get("items", []) if isinstance(history, dict) else []),
            "transfers": len(((history or {}).get("transferHistory") or {}).get("items", []) if isinstance(history, dict) else []),
        },
    }
    return record


def build_history_response(
    records: list[dict[str, Any]],
    *,
    requested_address: str | None = None,
    requested_wallet_hash: str | None = None,
    chain_id: int | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    first = records[0] if records else {}
    return {
        "schemaVersion": "mantlelens.assessment_history.v1",
        "walletAddress": first.get("walletAddress") or _normalize_address(requested_address),
        "walletHash": first.get("walletHash") or requested_wallet_hash,
        "chainId": first.get("chainId") or chain_id,
        "networkName": first.get("networkName") or (_network_name(int(chain_id)) if chain_id else None),
        "mode": mode or first.get("mode"),
        "recordCount": len(records),
        "records": records,
        "ordering": "scan_timestamp_desc",
        "generatedAt": _now(),
    }


def build_trend_response(
    records_asc: list[dict[str, Any]],
    *,
    requested_address: str | None = None,
    requested_wallet_hash: str | None = None,
    chain_id: int | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    first = records_asc[0] if records_asc else {}
    latest = records_asc[-1] if records_asc else {}
    status, notes = _trend_status(records_asc)
    delta = _trend_delta(records_asc[-2], records_asc[-1]) if len(records_asc) >= 2 else None
    source_changes = _source_coverage_changes(records_asc[-2], records_asc[-1]) if len(records_asc) >= 2 else []
    score_series = [_series_item(item, "riskScore") for item in records_asc]
    response = {
        "schemaVersion": "mantlelens.risk_trend.v1",
        "walletAddress": latest.get("walletAddress") or first.get("walletAddress") or _normalize_address(requested_address),
        "walletHash": latest.get("walletHash") or first.get("walletHash") or requested_wallet_hash,
        "chainId": latest.get("chainId") or first.get("chainId") or chain_id,
        "networkName": latest.get("networkName") or first.get("networkName") or (_network_name(int(chain_id)) if chain_id else None),
        "mode": mode or latest.get("mode") or first.get("mode"),
        "trendStatus": status,
        "status": status,
        "pointCount": len(records_asc),
        "recordCount": len(records_asc),
        "scoreSeries": score_series,
        "riskLevelSeries": [_series_item(item, "riskLevel") for item in records_asc],
        "confidenceSeries": [_series_item(item, "confidence") for item in records_asc],
        "statusSeries": [_series_item(item, "status") for item in records_asc],
        "sourceCoverageSeries": [
            {
                "assessmentId": item.get("assessmentId"),
                "timestamp": item.get("scanTimestamp"),
                "summary": item.get("sourceCoverageSummary", {}),
            }
            for item in records_asc
        ],
        "latestScoreDelta": delta.get("scoreDelta") if delta else None,
        "latestRiskLevelChange": delta.get("riskLevelChange") if delta else None,
        "sourceCoverageChanges": source_changes,
        "topRiskCategoryChanges": _top_risk_category_changes(records_asc[-2], records_asc[-1]) if len(records_asc) >= 2 else {"added": [], "removed": []},
        "trendSummary": _trend_summary(status, delta, source_changes, records_asc),
        "comparabilityNotes": notes,
        "points": [_legacy_point(item) for item in records_asc],
        "delta": delta,
        "generatedAt": _now(),
    }
    return response


def _filter_records(
    records: list[dict[str, Any]],
    *,
    address: str | None,
    wallet_hash: str | None,
    chain_id: int | None,
    mode: str | None,
) -> list[dict[str, Any]]:
    normalized_address = _normalize_address(address)
    filtered = []
    for record in records:
        if wallet_hash and record.get("walletHash") != wallet_hash:
            continue
        if not wallet_hash and normalized_address and record.get("walletAddress") != normalized_address:
            continue
        if chain_id is not None and int(record.get("chainId") or 0) != int(chain_id):
            continue
        if mode and record.get("mode") != mode:
            continue
        filtered.append(record)
    return filtered


def _same_wallet_key(record: dict[str, Any], address: str | None, chain_id: int, mode: str) -> bool:
    return record.get("walletAddress") == address and int(record.get("chainId") or 0) == int(chain_id) and record.get("mode") == mode


def _assessment_status(assessment: dict[str, Any]) -> str:
    data_status = str(assessment.get("dataStatus") or "PARTIAL_OR_UNKNOWN")
    if data_status == "COMPLETE" and str(assessment.get("riskLevel")) == "Low":
        return "SAFE"
    if data_status == "PARTIAL_OR_UNKNOWN":
        return "PARTIAL_OR_UNKNOWN"
    if str(assessment.get("riskLevel")) in {"High", "Critical"}:
        return "RISKY"
    if data_status == "ERROR":
        return "ERROR"
    return data_status


def _top_risk_summary(risk: dict[str, Any]) -> dict[str, Any]:
    return {
        "riskId": risk.get("riskId") or risk.get("risk_id"),
        "title": risk.get("title") or risk.get("claimText"),
        "category": risk.get("category") or risk.get("type"),
        "severity": risk.get("severity"),
        "scoreImpact": risk.get("scoreImpact") if risk.get("scoreImpact") is not None else risk.get("score_impact"),
        "confidence": risk.get("confidence"),
        "evidenceIds": risk.get("evidenceIds") or risk.get("evidence_ids") or [],
    }


def _commit_record_patch(commit_record: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(commit_record, dict):
        return {}
    return {
        "commitTxHash": commit_record.get("assessmentTx"),
        "commitStatus": commit_record.get("status"),
        "commitMode": commit_record.get("commitMode"),
        "commitExplorerUrl": commit_record.get("explorerUrl"),
        "assessmentContractAddress": commit_record.get("contractAddress"),
    }


def _commit_verification_patch(verification: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(verification, dict):
        return {}
    status = verification.get("verificationStatus") or verification.get("status")
    return {
        "commitTxHash": verification.get("txHash"),
        "commitVerificationStatus": status,
        "commitExplorerUrl": verification.get("explorerUrl"),
        "assessmentContractAddress": verification.get("contractAddress"),
    }


def _matches_assessment_or_commit(record: dict[str, Any], source: dict[str, Any]) -> bool:
    source_hash = source.get("assessmentHash") or source.get("localAssessmentHash")
    if source_hash and record.get("assessmentHash") == source_hash:
        return True
    source_id = source.get("assessmentId") or source.get("localAssessmentId")
    if source_id and record.get("assessmentId") == source_id:
        return True
    tx_hash = source.get("assessmentTx") or source.get("txHash")
    if tx_hash and record.get("commitTxHash") == tx_hash:
        return True
    return False


def _source_coverage_summary(coverage: dict[str, Any]) -> dict[str, Any]:
    source_availability = coverage.get("sourceAvailability", {})
    data_completeness = coverage.get("dataCompleteness", {})
    summary = {
        "available": 0,
        "partial": 0,
        "unknown": 0,
        "unavailable": 0,
        "source_failed": 0,
        "statuses": {},
        "dataCompleteness": dict(data_completeness),
    }
    for name, source in source_availability.items():
        status = source.get("status") if isinstance(source, dict) else source
        status_text = str(status or "unknown")
        if status_text not in summary:
            summary[status_text] = 0
        summary[status_text] += 1
        summary["statuses"][name] = status_text
    return summary


def _trend_status(records_asc: list[dict[str, Any]]) -> tuple[str, list[str]]:
    if len(records_asc) < 2:
        return "insufficient_history", ["Need at least two comparable assessments to show trend."]
    previous, current = records_asc[-2], records_asc[-1]
    changes = _source_coverage_changes(previous, current)
    degraded = [item for item in changes if item["direction"] == "degraded"]
    improved = [item for item in changes if item["direction"] == "improved"]
    if degraded:
        return "partially_comparable", [
            "Trend is partially comparable because source coverage changed.",
            "Risk score changes are not treated as confirmed improvement when data coverage degrades.",
        ]
    if improved:
        return "partially_comparable", ["Trend is partially comparable because source coverage changed."]
    if previous.get("mode") != current.get("mode") or previous.get("chainId") != current.get("chainId"):
        return "not_comparable", ["Trend records span different modes or chains."]
    return "comparable", ["Source coverage is stable enough for cautious comparison."]


def _trend_delta(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    previous_categories = set(previous.get("riskCategories", []))
    current_categories = list(current.get("riskCategories", []))
    score_delta = round(float(current.get("riskScore") or 0) - float(previous.get("riskScore") or 0), 2)
    return {
        "scoreDelta": score_delta,
        "dataConfidenceDelta": round(float(current.get("confidence") or 0) - float(previous.get("confidence") or 0), 2),
        "riskLevelChanged": current.get("riskLevel") != previous.get("riskLevel"),
        "riskLevelChange": {
            "previous": previous.get("riskLevel"),
            "current": current.get("riskLevel"),
            "direction": _level_direction(previous.get("riskLevel"), current.get("riskLevel")),
        },
        "previousRiskLevel": previous.get("riskLevel"),
        "currentRiskLevel": current.get("riskLevel"),
        "newTopRiskIds": [
            item.get("riskId")
            for item in current.get("topRiskSummaries", [])
            if item.get("riskId") not in {risk.get("riskId") for risk in previous.get("topRiskSummaries", [])}
        ],
        "newTopRiskCategories": [category for category in current_categories if category not in previous_categories],
        "previousAssessmentHash": previous.get("assessmentHash"),
        "currentAssessmentHash": current.get("assessmentHash"),
        "improvementConfirmed": score_delta < 0 and not any(item["direction"] == "degraded" for item in _source_coverage_changes(previous, current)),
    }


def _source_coverage_changes(previous: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    previous_statuses = (previous.get("sourceCoverageSummary") or {}).get("statuses", {})
    current_statuses = (current.get("sourceCoverageSummary") or {}).get("statuses", {})
    names = sorted(set(previous_statuses) | set(current_statuses))
    changes = []
    for name in names:
        before = previous_statuses.get(name, "unknown")
        after = current_statuses.get(name, "unknown")
        if before == after:
            continue
        before_rank = SOURCE_ORDER.get(str(before), 2)
        after_rank = SOURCE_ORDER.get(str(after), 2)
        changes.append(
            {
                "source": name,
                "previous": before,
                "current": after,
                "direction": "degraded" if after_rank < before_rank else "improved",
            }
        )
    return changes


def _top_risk_category_changes(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, list[str]]:
    previous_categories = set(previous.get("riskCategories", []))
    current_categories = set(current.get("riskCategories", []))
    return {
        "added": sorted(current_categories - previous_categories),
        "removed": sorted(previous_categories - current_categories),
    }


def _trend_summary(status: str, delta: dict[str, Any] | None, source_changes: list[dict[str, Any]], records: list[dict[str, Any]]) -> str:
    if status == "insufficient_history":
        return "Need at least two comparable assessments to show trend."
    if not delta:
        return "Trend cannot be summarized yet."
    degraded = [item for item in source_changes if item["direction"] == "degraded"]
    score_delta = float(delta.get("scoreDelta") or 0)
    if score_delta < 0 and degraded:
        return "Risk score decreased, but source coverage also degraded, so improvement is not confirmed."
    if score_delta < 0:
        return "Risk score decreased under stable enough coverage; review evidence before calling this safer."
    if score_delta > 0:
        return "Risk score increased; review new risks and evidence before taking action."
    if degraded:
        return "Risk score was unchanged, but source coverage degraded, so uncertainty increased."
    return "Risk score was unchanged across the latest assessments."


def _series_item(record: dict[str, Any], key: str) -> dict[str, Any]:
    return {
        "assessmentId": record.get("assessmentId"),
        "timestamp": record.get("scanTimestamp"),
        "value": record.get(key),
    }


def _legacy_point(record: dict[str, Any]) -> dict[str, Any]:
    top_ids = [item.get("riskId") for item in record.get("topRiskSummaries", []) if item.get("riskId")]
    return {
        "assessmentId": record.get("assessmentId"),
        "timestamp": record.get("scanTimestamp"),
        "walletRiskScore": record.get("riskScore"),
        "riskLevel": record.get("riskLevel"),
        "dataConfidence": record.get("confidence"),
        "dataStatus": record.get("status"),
        "dataMode": record.get("mode"),
        "chainId": record.get("chainId"),
        "assessmentHash": record.get("assessmentHash"),
        "evidenceBundleHash": record.get("evidenceBundleHash"),
        "topRiskIds": top_ids,
    }


def _level_direction(previous: Any, current: Any) -> str:
    previous_rank = LEVEL_ORDER.get(str(previous), 0)
    current_rank = LEVEL_ORDER.get(str(current), 0)
    if current_rank > previous_rank:
        return "worsened"
    if current_rank < previous_rank:
        return "improved"
    return "unchanged"


def _network_name(chain_id: int) -> str:
    if chain_id == 5003:
        return "Mantle Sepolia"
    if chain_id == 5000:
        return "Mantle Mainnet"
    return f"Mantle Chain {chain_id}"


def _normalize_address(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if text.startswith("0x"):
        return text.lower()
    return text


def _state_db_path() -> str:
    return os.getenv("MANTLELENS_STATE_DB", "data/mantlelens.sqlite3")


def _use_memory_store() -> bool:
    return os.getenv("MANTLELENS_DISABLE_PERSISTENCE", "").strip().lower() in {"1", "true", "yes", "on"}


ASSESSMENT_HISTORY_STORE = (
    InMemoryAssessmentHistoryStore() if _use_memory_store() else SQLiteAssessmentHistoryStore(_state_db_path())
)
