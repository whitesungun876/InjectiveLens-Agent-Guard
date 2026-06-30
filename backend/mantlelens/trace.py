from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class TraceEvent:
    event_type: str
    run_id: str
    trace_id: str
    from_state: str | None
    to_state: str | None
    policy_decision: str
    message: str
    tool_name: str | None = None
    workflow_name: str | None = None
    duration_ms: int | None = None
    created_at: str = field(default_factory=utc_now)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "eventType": self.event_type,
            "runId": self.run_id,
            "traceId": self.trace_id,
            "fromState": self.from_state,
            "toState": self.to_state,
            "policyDecision": self.policy_decision,
            "message": self.message,
            "toolName": self.tool_name,
            "workflowName": self.workflow_name,
            "durationMs": self.duration_ms,
            "createdAt": self.created_at,
            "details": self.details,
        }


class TraceRecorder:
    def __init__(self, run_id: str | None = None, trace_id: str | None = None) -> None:
        self.run_id = run_id or f"run_{uuid4().hex}"
        self.trace_id = trace_id or f"trace_{uuid4().hex}"
        self.events: list[TraceEvent] = []

    def record(
        self,
        event_type: str,
        message: str,
        *,
        from_state: str | None = None,
        to_state: str | None = None,
        policy_decision: str = "allow",
        tool_name: str | None = None,
        workflow_name: str | None = None,
        duration_ms: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.events.append(
            TraceEvent(
                event_type=event_type,
                run_id=self.run_id,
                trace_id=self.trace_id,
                from_state=from_state,
                to_state=to_state,
                policy_decision=policy_decision,
                message=message,
                tool_name=tool_name,
                workflow_name=workflow_name,
                duration_ms=duration_ms,
                details=details or {},
            )
        )

    def timed_tool(self, tool_name: str, fn, *args, **kwargs):
        start = perf_counter()
        result = fn(*args, **kwargs)
        duration_ms = int((perf_counter() - start) * 1000)
        self.record(
            "tool_call_completed",
            f"{tool_name} completed",
            tool_name=tool_name,
            duration_ms=duration_ms,
            details={
                "sourceStatus": result.source_status,
                "dataCoverage": result.data_coverage,
            },
        )
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "traceId": self.trace_id,
            "events": [event.to_dict() for event in self.events],
        }
