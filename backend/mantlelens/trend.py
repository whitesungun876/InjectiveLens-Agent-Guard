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
class InMemoryTrendStore:
    max_points_per_wallet: int = 20
    _points_by_wallet: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def record_assessment(
        self,
        assessment: dict[str, Any],
        evidence_bundle: dict[str, Any],
    ) -> dict[str, Any]:
        wallet_hash = assessment["wallet"]["walletHash"]
        point = _assessment_to_point(assessment, evidence_bundle)
        with self._lock:
            points = self._points_by_wallet.setdefault(wallet_hash, [])
            points.append(point)
            if len(points) > self.max_points_per_wallet:
                del points[: len(points) - self.max_points_per_wallet]
            visible_points = [dict(item) for item in points]
        return _build_trend(wallet_hash, visible_points)

    def history(self, wallet_hash: str) -> dict[str, Any]:
        with self._lock:
            visible_points = [dict(item) for item in self._points_by_wallet.get(wallet_hash, [])]
        return _build_trend(wallet_hash, visible_points)

    def reset(self, wallet_hash: str | None = None) -> None:
        with self._lock:
            if wallet_hash is None:
                self._points_by_wallet.clear()
            else:
                self._points_by_wallet.pop(wallet_hash, None)


class SQLiteTrendStore:
    """Durable trend history for demo/prod runs.

    The in-memory store is still available for unit tests, but the default app
    store persists across process restarts so risk trend history is not lost
    when the local server is restarted.
    """

    def __init__(self, db_path: str | os.PathLike[str], max_points_per_wallet: int = 50) -> None:
        self.db_path = str(db_path)
        self.max_points_per_wallet = max_points_per_wallet
        self._lock = Lock()
        self._ensure_schema()

    def record_assessment(
        self,
        assessment: dict[str, Any],
        evidence_bundle: dict[str, Any],
    ) -> dict[str, Any]:
        wallet_hash = assessment["wallet"]["walletHash"]
        point = _assessment_to_point(assessment, evidence_bundle)
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO trend_points (wallet_hash, assessment_hash, timestamp, point_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        wallet_hash,
                        point["assessmentHash"],
                        point["timestamp"],
                        json.dumps(point, sort_keys=True),
                    ),
                )
                stale_ids = [
                    row[0]
                    for row in conn.execute(
                        """
                        SELECT id
                        FROM trend_points
                        WHERE wallet_hash = ?
                        ORDER BY id DESC
                        LIMIT -1 OFFSET ?
                        """,
                        (wallet_hash, self.max_points_per_wallet),
                    ).fetchall()
                ]
                if stale_ids:
                    conn.executemany("DELETE FROM trend_points WHERE id = ?", [(row_id,) for row_id in stale_ids])
            visible_points = self._points(wallet_hash)
        return _build_trend(wallet_hash, visible_points, source="sqlite_assessment_history")

    def history(self, wallet_hash: str) -> dict[str, Any]:
        return _build_trend(wallet_hash, self._points(wallet_hash), source="sqlite_assessment_history")

    def reset(self, wallet_hash: str | None = None) -> None:
        with self._lock:
            with self._connect() as conn:
                if wallet_hash is None:
                    conn.execute("DELETE FROM trend_points")
                else:
                    conn.execute("DELETE FROM trend_points WHERE wallet_hash = ?", (wallet_hash,))

    def _points(self, wallet_hash: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT point_json
                FROM trend_points
                WHERE wallet_hash = ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (wallet_hash, self.max_points_per_wallet),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(self.db_path)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trend_points (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wallet_hash TEXT NOT NULL,
                    assessment_hash TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    point_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_trend_wallet_id ON trend_points(wallet_hash, id)"
            )


def _assessment_to_point(
    assessment: dict[str, Any],
    evidence_bundle: dict[str, Any],
) -> dict[str, Any]:
    top_risk_ids = [
        risk["riskId"]
        for risk in assessment.get("topRisks", [])
        if isinstance(risk, dict) and risk.get("riskId")
    ]
    evidence_bundle_hash = evidence_bundle.get("evidenceBundleHash") or assessment.get("evidenceBundleHash")
    point = {
        "assessmentId": assessment["assessmentId"],
        "timestamp": assessment.get("timestamp") or _now(),
        "walletRiskScore": assessment["walletRiskScore"],
        "riskLevel": assessment["riskLevel"],
        "dataConfidence": assessment["dataConfidence"],
        "dataStatus": assessment["dataStatus"],
        "dataMode": assessment["dataMode"],
        "chainId": assessment["chainId"],
        "assessmentHash": assessment["assessmentHash"],
        "evidenceBundleHash": evidence_bundle_hash,
        "topRiskIds": top_risk_ids,
    }
    point["trendPointHash"] = stable_hash(
        {
            "assessmentHash": point["assessmentHash"],
            "evidenceBundleHash": point["evidenceBundleHash"],
            "topRiskIds": point["topRiskIds"],
            "walletRiskScore": point["walletRiskScore"],
        }
    )
    return point


def _build_trend(
    wallet_hash: str,
    points: list[dict[str, Any]],
    *,
    source: str = "in_memory_assessment_history",
) -> dict[str, Any]:
    status = "available" if len(points) >= 2 else "insufficient_history"
    return {
        "walletHash": wallet_hash,
        "status": status,
        "source": source,
        "pointCount": len(points),
        "generatedAt": _now(),
        "points": points,
        "delta": _delta(points[-2], points[-1]) if len(points) >= 2 else None,
    }


def _delta(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    previous_ids = set(previous.get("topRiskIds", []))
    current_ids = list(current.get("topRiskIds", []))
    return {
        "scoreDelta": round(
            float(current["walletRiskScore"]) - float(previous["walletRiskScore"]),
            2,
        ),
        "dataConfidenceDelta": round(
            float(current["dataConfidence"]) - float(previous["dataConfidence"]),
            2,
        ),
        "riskLevelChanged": current["riskLevel"] != previous["riskLevel"],
        "previousRiskLevel": previous["riskLevel"],
        "currentRiskLevel": current["riskLevel"],
        "newTopRiskIds": [risk_id for risk_id in current_ids if risk_id not in previous_ids],
        "previousAssessmentHash": previous["assessmentHash"],
        "currentAssessmentHash": current["assessmentHash"],
    }


def _state_db_path() -> str:
    return os.getenv("MANTLELENS_STATE_DB", "data/mantlelens.sqlite3")


def _use_memory_store() -> bool:
    return os.getenv("MANTLELENS_DISABLE_PERSISTENCE", "").strip().lower() in {"1", "true", "yes", "on"}


TREND_STORE = InMemoryTrendStore() if _use_memory_store() else SQLiteTrendStore(_state_db_path())
