from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = ROOT / "frontend/app/src/App.tsx"
COPY_SOURCE = ROOT / "frontend/app/src/presentation/assessmentCopy.ts"
TYPES_SOURCE = ROOT / "frontend/app/src/types.ts"


class P27BAgentDecisionAuditTest(unittest.TestCase):
    def test_decision_audit_contract_and_copy_layer_exist(self) -> None:
        types = TYPES_SOURCE.read_text(encoding="utf-8")
        copy = COPY_SOURCE.read_text(encoding="utf-8")

        for name in (
            "DecisionAudit",
            "DecisionAuditReason",
            "DecisionAuditRule",
            "DecisionAuditAction",
        ):
            self.assertIn(f"export type {name}", types)

        for helper in (
            "getDecisionAudit",
            "getDecisionLabel",
            "getActionLabel",
            "getBlockedActions",
            "getAllowedActions",
            "getDecisionReasons",
            "getHardRules",
        ):
            self.assertIn(f"export function {helper}", copy)

    def test_review_approval_audit_binds_evidence_and_rules(self) -> None:
        copy = COPY_SOURCE.read_text(encoding="utf-8")

        self.assertIn('return "REVIEW_APPROVAL";', copy)
        self.assertIn('return "SIMULATE_REVOKE_APPROVAL";', copy)
        self.assertIn("Active allowance confirmed", copy)
        self.assertIn("Spender label unavailable", copy)
        self.assertIn("evidenceIds: approvalIds", copy)
        self.assertIn("rule:unknown_spender_not_safe", copy)
        self.assertIn("rule:p0_real_execution_blocked", copy)

    def test_transfer_only_audit_does_not_fall_back_to_approval_or_revoke(self) -> None:
        copy = COPY_SOURCE.read_text(encoding="utf-8")
        app = APP_SOURCE.read_text(encoding="utf-8")

        self.assertIn('case "REVIEW_TRANSFER_EVIDENCE":', copy)
        self.assertIn('return "Review transfer evidence";', copy)
        self.assertIn('case "CHECK_SOURCE_COVERAGE_INSPECT_TRANSFER":', copy)
        self.assertIn('return "Check source coverage / Inspect transfer evidence";', copy)
        self.assertIn('if (hasTransferSignal(assessment)) return "REVIEW_TRANSFER_EVIDENCE";', copy)
        self.assertIn('decisionType === "REVIEW_TRANSFER_EVIDENCE"', copy)
        self.assertIn("if (scan) return hasActiveApprovalEvidence", copy)
        self.assertIn('if (simulation.available) return "SIMULATE_REVOKE_APPROVAL";', copy)
        self.assertIn("Transfer evidence requires review", copy)
        self.assertIn("no active approval or yield action found to simulate".lower(), copy.lower())
        self.assertIn("<small>Simulation</small>", app)
        self.assertIn("Reason: {simulation.reason}", app)

    def test_partial_or_quiet_wallet_is_not_marked_safe_without_sufficient_coverage(self) -> None:
        copy = COPY_SOURCE.read_text(encoding="utf-8")

        self.assertIn(
            'if (isCoverageOnlyAssessment(assessment) || isPartialOrUnknown(assessment.dataStatus)) return "RECORD_ASSESSMENT_ONLY";',
            copy,
        )
        self.assertIn('if (hasTransferSignal(assessment)) return "REVIEW_TRANSFER_EVIDENCE";', copy)
        self.assertIn('if (!directSignalCount(assessment) && hasSufficientCoverage(assessment)) return "WATCH";', copy)
        self.assertNotIn('if (!directSignalCount(assessment)) return "SAFE";', copy)
        self.assertNotIn('if (isCoverageOnlyAssessment(assessment)) return "SAFE";', copy)

    def test_blocked_actions_include_real_execution_boundaries(self) -> None:
        copy = COPY_SOURCE.read_text(encoding="utf-8")

        for blocked in (
            "Real revoke",
            "Swap",
            "Transfer",
            "Auto-signing",
            "Private-key custody",
            "LLM-generated transaction execution",
        ):
            self.assertIn(blocked, copy)

    def test_llm_boundary_and_unknown_not_safe_copy_exist(self) -> None:
        copy = COPY_SOURCE.read_text(encoding="utf-8")
        app = APP_SOURCE.read_text(encoding="utf-8")

        self.assertIn("Rules and evidence run before LLM explanation.", copy)
        self.assertIn("LLM explains findings; it does not execute transactions or override hard rules.", copy)
        self.assertIn("Missing indexed data cannot reduce risk to safe.", copy)
        self.assertIn("Proof is not safety", copy)
        self.assertIn("Safety boundary", app)

    def test_evidence_and_advanced_surfaces_render_decision_audit(self) -> None:
        app = APP_SOURCE.read_text(encoding="utf-8")

        self.assertIn('data-testid="decision-audit-card"', app)
        self.assertIn("View decision details", app)
        self.assertIn('data-testid="advanced-decision-audit"', app)
        self.assertIn("Decision", app)
        self.assertIn("Action", app)
        self.assertIn("Supporting evidence", app)
        self.assertIn("Raw developer trace", app)
        self.assertIn("Triggered hard rules", app)
        self.assertIn("items={triggeredRules.map((rule) => `${rule.label}: ${rule.description}`)}", app)
        self.assertIn("triggeredRules.map((rule) => rule.id).join", app)
        self.assertIn("Blocked actions", app)
        self.assertIn("Allowed actions", app)

    def test_advanced_does_not_expose_send_revoke_wallet_action(self) -> None:
        app = APP_SOURCE.read_text(encoding="utf-8")
        advanced_start = app.index("function AdvancedView")
        advanced_end = app.index("function EvidenceView")
        advanced_view = app[advanced_start:advanced_end]

        self.assertNotIn("Send revoke with wallet", advanced_view)
        self.assertNotIn("eth_sendTransaction", advanced_view)
        self.assertIn("review-only revoke context", app)

    def test_overview_is_not_polluted_with_debug_or_rule_tree(self) -> None:
        app = APP_SOURCE.read_text(encoding="utf-8")
        summary_start = app.index("function SummaryView")
        summary_end = app.index("function MantleNativeSignalsPanel")
        summary_view = app[summary_start:summary_end]

        self.assertNotIn("DecisionAuditSummaryCard", summary_view)
        self.assertNotIn("Decision Audit", summary_view)
        self.assertNotIn("Raw developer trace", summary_view)
        self.assertNotIn("Triggered hard rules", summary_view)
        self.assertNotIn("benchmark-case-meta", summary_view)

    def test_p2_7a_live_proof_copy_remains_intact(self) -> None:
        app = APP_SOURCE.read_text(encoding="utf-8")
        copy = COPY_SOURCE.read_text(encoding="utf-8")

        self.assertIn("Assessment hash submitted. Click Verify assessment to confirm matched.", app)
        self.assertIn("Mantle Sepolia", app)
        self.assertIn("AssessmentRecorded", app)
        self.assertIn("Mantle Sepolia AssessmentLogger", copy)


if __name__ == "__main__":
    unittest.main()
