from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Lock
from typing import Any
from uuid import uuid4


CORE_EVENTS = {
    "scan_started",
    "risk_evaluation_completed",
    "risk_trend_recorded",
    "alerts_evaluated",
    "evidence_bundle_built",
    "explanation_completed",
    "simulation_completed",
    "assessment_commit_status_changed",
    "benchmark_history_viewed",
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class EventRecorder:
    events: list[dict[str, Any]] = field(default_factory=list)
    lock: Lock = field(default_factory=Lock)

    def record(
        self,
        event_name: str,
        *,
        run_id: str,
        trace_id: str,
        wallet_hash: str,
        assessment_id: str | None = None,
        state: str = "UNKNOWN",
        data_mode: str = "demo",
        properties: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = {
            "eventName": event_name,
            "eventVersion": "1.0",
            "eventId": f"evt_{uuid4().hex}",
            "occurredAt": _now(),
            "runId": run_id,
            "traceId": trace_id,
            "assessmentId": assessment_id,
            "walletHash": wallet_hash,
            "chainId": 5000,
            "dataMode": data_mode,
            "state": state,
            "properties": properties or {},
        }
        with self.lock:
            self.events.append(event)
        return event

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.lock:
            return list(self.events[-limit:])


EVENTS = EventRecorder()


def validate_core_event_traceability(events: list[dict[str, Any]]) -> bool:
    for event in events:
        if event.get("eventName") in CORE_EVENTS:
            if not event.get("runId") or not event.get("traceId"):
                return False
    return True
