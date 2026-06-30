from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any


READ_ONLY_TOOLS = {
    "getNativeBalance",
    "getKnownTokenBalances",
    "getTokenApprovals",
    "confirmActiveAllowance",
    "getSpenderLabels",
    "getTransactionCount",
    "getTransferLogs",
    "getTokenPrices",
    "getTokenSecurity",
    "getRwaYieldExposure",
}

ANALYTICAL_TOOLS = {
    "evaluateWalletRisk",
    "buildEvidenceBundle",
    "explainAssessment",
}

STATE_CHANGING_TOOLS = {
    "commitAssessment",
    "recordOutcome",
}

FORBIDDEN_REAL_EXECUTION_TOOLS = {
    "revokeApproval",
    "swapToken",
    "executeTrade",
    "transferAsset",
}

ALLOWED_TRANSITIONS = {
    "INIT": {"DATA_GATHERING", "FAILED_RETRYABLE"},
    "DATA_GATHERING": {"RISK_EVALUATING", "PARTIAL_OR_UNKNOWN", "FAILED_RETRYABLE"},
    "PARTIAL_OR_UNKNOWN": {"RISK_EVALUATING", "EXPLAINING"},
    "RISK_EVALUATING": {"EVIDENCE_BINDING", "FAILED_RETRYABLE"},
    "EVIDENCE_BINDING": {"EXPLAINING", "PARTIAL_OR_UNKNOWN"},
    "EXPLAINING": {"SIMULATION_READY", "FAILED_RETRYABLE"},
    "SIMULATION_READY": {"SIMULATING", "READY_TO_COMMIT"},
    "SIMULATING": {"READY_TO_COMMIT", "FAILED_RETRYABLE"},
    "READY_TO_COMMIT": {"COMMIT_PENDING"},
    "COMMIT_PENDING": {"COMMITTED", "PENDING_RETRY"},
    "PENDING_RETRY": {"COMMITTED", "FAILED_RETRYABLE"},
    "COMMITTED": {"BENCHMARK_UPDATED"},
    "BENCHMARK_UPDATED": set(),
    "FAILED_RETRYABLE": set(),
}


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    decision: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "decision": self.decision,
            "reason": self.reason,
        }


class PolicyEngine:
    def __init__(self, max_steps: int = 10, max_repeat_calls: int = 2) -> None:
        self.max_steps = max_steps
        self.max_repeat_calls = max_repeat_calls
        self.step_count = 0
        self.tool_calls: Counter[tuple[str, str]] = Counter()

    def allow_transition(self, from_state: str, to_state: str) -> PolicyDecision:
        allowed_targets = ALLOWED_TRANSITIONS.get(from_state, set())
        if to_state not in allowed_targets:
            return PolicyDecision(False, "block", f"Transition {from_state}->{to_state} is not allowed")
        self.step_count += 1
        if self.step_count > self.max_steps:
            return PolicyDecision(False, "block", "Agent step budget exceeded")
        return PolicyDecision(True, "allow", "Transition allowed")

    def allow_tool_call(
        self,
        tool_name: str,
        arguments_hash: str,
        *,
        current_state: str,
        requires_confirmation: bool = False,
        confirmation_received: bool = False,
        idempotency_key: str | None = None,
    ) -> PolicyDecision:
        if tool_name in FORBIDDEN_REAL_EXECUTION_TOOLS:
            return PolicyDecision(False, "block", "P0 forbids real revoke, swap, trade, and asset transfer")

        call_key = (tool_name, arguments_hash)
        self.tool_calls[call_key] += 1
        if self.tool_calls[call_key] > self.max_repeat_calls:
            return PolicyDecision(False, "block", "Repeated tool call blocked")

        if tool_name in STATE_CHANGING_TOOLS:
            if current_state not in {"READY_TO_COMMIT", "COMMIT_PENDING"}:
                return PolicyDecision(False, "block", "State-changing tool is not allowed in current state")
            if requires_confirmation and not confirmation_received:
                return PolicyDecision(False, "block", "State-changing tool requires confirmation")
            if not idempotency_key:
                return PolicyDecision(False, "block", "State-changing tool requires idempotency key")
            return PolicyDecision(True, "allow", "Hash-recording tool allowed")

        if tool_name in READ_ONLY_TOOLS or tool_name in ANALYTICAL_TOOLS:
            return PolicyDecision(True, "allow", "Tool allowed")

        return PolicyDecision(False, "block", f"Unknown tool {tool_name}")
