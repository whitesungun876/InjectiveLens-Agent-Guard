"""MantleLens Wallet Guard MVP backend primitives."""

from .adapters import FixtureWalletAdapter
from .analytics import EVENTS, EventRecorder, validate_core_event_traceability
from .evidence import EvidenceBindingError, build_evidence_bundle, validate_evidence_binding
from .explain import rule_based_explanation
from .fixtures import FixtureRepository
from .ledger import LEDGER, InMemoryLedger
from .llm_guard import guarded_explanation, validate_llm_claims
from .policy import PolicyEngine
from .protocol import agent_card, agent_registration, call_mcp_tool, mcp_call_response, mcp_list_response, mcp_tools
from .risk import evaluate_wallet_risk
from .simulation import simulate_approval_revoke, simulate_portfolio_adjustment
from .trace import TraceRecorder
from .workflows import WalletGuardRunner, WorkflowError

__all__ = [
    "EVENTS",
    "EvidenceBindingError",
    "EventRecorder",
    "FixtureRepository",
    "FixtureWalletAdapter",
    "InMemoryLedger",
    "LEDGER",
    "PolicyEngine",
    "TraceRecorder",
    "WalletGuardRunner",
    "WorkflowError",
    "agent_card",
    "agent_registration",
    "build_evidence_bundle",
    "call_mcp_tool",
    "evaluate_wallet_risk",
    "guarded_explanation",
    "mcp_call_response",
    "mcp_list_response",
    "mcp_tools",
    "rule_based_explanation",
    "simulate_approval_revoke",
    "simulate_portfolio_adjustment",
    "validate_core_event_traceability",
    "validate_evidence_binding",
    "validate_llm_claims",
]
