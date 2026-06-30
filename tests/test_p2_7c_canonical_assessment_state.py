from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = ROOT / "frontend/app/src/App.tsx"
VIEW_MODEL_SOURCE = ROOT / "frontend/app/src/presentation/assessmentViewModel.ts"
COPY_SOURCE = ROOT / "frontend/app/src/presentation/assessmentCopy.ts"


class P27CCanonicalAssessmentStateTest(unittest.TestCase):
    def test_view_model_contract_contains_required_fields_and_helpers(self) -> None:
        source = VIEW_MODEL_SOURCE.read_text(encoding="utf-8")

        self.assertIn("export type AssessmentViewModel", source)
        for field in (
            "scanMode",
            "targetLabel",
            "chainId",
            "walletAddress",
            "walletHash",
            "evidenceClass",
            "headline",
            "subheadline",
            "scoreDisplay",
            "severity",
            "topSignals",
            "coverage",
            "recordStatus",
            "proofKind",
            "proofStatus",
            "currentAssessmentTx",
            "previousVerifiedAssessmentTx",
            "previousVerifiedAssessmentHash",
            "historyScope",
            "nextStep",
        ):
            self.assertIn(field, source)

        for helper in (
            "buildAssessmentViewModel",
            "deriveProofStatus",
            "deriveRecordStatus",
            "deriveRecordability",
            "deriveEvidenceClass",
            "getRecordability",
            "getProofState",
            "getRecordStatus",
            "filterHistoryRecordsForViewModel",
        ):
            self.assertIn(f"export function {helper}", source)

    def test_live_scan_never_renders_replay_proof_only(self) -> None:
        source = VIEW_MODEL_SOURCE.read_text(encoding="utf-8")

        self.assertIn('if (scanMode !== "live")', source)
        self.assertIn('status: "replay_only"', source)
        self.assertIn('if (recordStatus === "ready_to_record")', source)
        self.assertIn('status: "ready_to_record"', source)
        self.assertNotIn('scanMode === "live" && status: "replay_only"', source)

    def test_demo_replay_can_render_replay_proof_only(self) -> None:
        source = VIEW_MODEL_SOURCE.read_text(encoding="utf-8")

        self.assertIn('kind: "replay"', source)
        self.assertIn('label: "Replay proof only"', source)
        self.assertIn('actionLabel: "View replay proof"', source)

    def test_approval_signal_prevents_no_direct_evidence_headline(self) -> None:
        source = VIEW_MODEL_SOURCE.read_text(encoding="utf-8")

        self.assertIn('signals.push(signalFromRisk("approval", "Approval anomaly", approval));', source)
        self.assertIn('if (signals.length) return getRiskHeadline(assessment, signals.length);', source)
        self.assertIn('return "No direct on-chain risk signals found";', source)

    def test_coverage_limited_unknown_only_shows_coverage_signals(self) -> None:
        source = VIEW_MODEL_SOURCE.read_text(encoding="utf-8")

        self.assertIn('if (!signals.length)', source)
        self.assertIn('signals.push(signalFromRisk("coverage", "Source coverage warning", coverage));', source)
        self.assertIn('if (signals.some((signal) => signal.key !== "coverage")) return "direct_risk_found";', source)
        self.assertIn('return "coverage_limited_unknown";', source)

    def test_not_enough_data_replaces_numeric_score_for_coverage_limited_unknown(self) -> None:
        source = VIEW_MODEL_SOURCE.read_text(encoding="utf-8")

        self.assertIn('if (evidenceClass === "coverage_limited_unknown")', source)
        self.assertIn('kind: "not_enough_data"', source)
        self.assertIn('value: "Not enough data"', source)
        self.assertIn("0 detected risk signals · not a safety score", source)
        self.assertIn("isSafetyScore: false", source)

    def test_numeric_high_score_includes_override_explanation(self) -> None:
        source = VIEW_MODEL_SOURCE.read_text(encoding="utf-8")
        app = APP_SOURCE.read_text(encoding="utf-8")

        self.assertIn("High severity due to rule override; numeric score reflects limited direct-loss evidence.", source)
        self.assertIn("score.overrideExplanation || score.helper", app)

    def test_coverage_is_not_outcome_and_history_filters_current_mode(self) -> None:
        source = VIEW_MODEL_SOURCE.read_text(encoding="utf-8")
        app = APP_SOURCE.read_text(encoding="utf-8")

        self.assertIn('"current_live_wallet"', source)
        self.assertIn('"current_replay_scenario"', source)
        self.assertIn('if (viewModel.historyScope === "current_live_wallet") return record.mode === "live";', source)
        self.assertIn('if (viewModel.historyScope === "current_replay_scenario") return record.mode !== "live";', source)
        self.assertIn("filterHistoryRecordsForViewModel(viewModel, history?.records || [])", app)
        self.assertIn("Outcome: {recordOutcomeLabel(record, count)} · Coverage: {recordCoverageLabel(record)}", app)

    def test_previous_verified_assessment_is_separate_from_current_scan(self) -> None:
        source = VIEW_MODEL_SOURCE.read_text(encoding="utf-8")
        app = APP_SOURCE.read_text(encoding="utf-8")

        self.assertIn("previousVerifiedAssessmentTx", source)
        self.assertIn('"previous_verified_available"', source)
        self.assertIn("Current assessment: Not recorded on-chain", source)
        self.assertIn("Previous verified assessment: Available", source)
        self.assertIn("SEPOLIA_JUDGE_ASSESSMENT_TX", source)
        self.assertIn("SEPOLIA_JUDGE_ASSESSMENT_HASH", source)
        self.assertIn('data-testid="history-current-proof-note"', app)

    def test_known_judge_live_tx_is_loaded_as_matching_verified_proof(self) -> None:
        source = VIEW_MODEL_SOURCE.read_text(encoding="utf-8")
        app = APP_SOURCE.read_text(encoding="utf-8")

        self.assertIn("knownLiveDemoProof: true", source)
        self.assertIn("isKnownSepoliaProofForAssessment", source)
        self.assertIn("findMatchingOnchainRecord", source)
        self.assertIn('"verified_matched"', source)
        self.assertIn('"AssessmentRecorded"', source)
        self.assertIn("https://sepolia.mantlescan.xyz/tx/${SEPOLIA_JUDGE_ASSESSMENT_TX}", source)
        self.assertIn("viewModel.proofStatus === \"verified_matched\"", app)
        self.assertIn('data-testid="verify-onchain-record"', app)

    def test_history_uses_verified_live_proof_labels(self) -> None:
        app = APP_SOURCE.read_text(encoding="utf-8")

        self.assertIn("historyProofSummary(latestRecord, viewModel)", app)
        self.assertIn("recordHasCurrentVerifiedProof", app)
        self.assertIn('return "AssessmentRecorded";', app)
        self.assertIn('return "Recorded on Mantle Sepolia";', app)
        self.assertIn('label="View on-chain proof"', app)
        self.assertIn("Current proof applies to latest assessment.", app)
        self.assertNotIn("sameWallet && Number(record.chainId)", app)
        self.assertIn("currentProofRecordId", app)
        self.assertIn("recordUsesLatestProofButIsNotCurrent", app)
        self.assertIn('return "Historical local record";', app)
        self.assertIn('return "Not recorded on-chain";', app)

    def test_onchain_panel_shows_verified_proof_state_details(self) -> None:
        app = APP_SOURCE.read_text(encoding="utf-8")

        self.assertIn('data-testid="verified-proof-state"', app)
        self.assertIn("Verified proof", app)
        self.assertIn("AssessmentRecorded", app)
        self.assertIn("matched", app)
        self.assertIn("Mantle Sepolia · 5003", app)
        self.assertIn("AssessmentLogger", app)
        self.assertIn("Mantlescan", app)
        self.assertIn("Local assessmentHash", app)
        self.assertIn("On-chain assessmentHash", app)

    def test_live_history_records_never_render_replay_proof_only(self) -> None:
        app = APP_SOURCE.read_text(encoding="utf-8")

        self.assertIn("function isLiveHistoryRecord", app)
        self.assertIn('if (isLiveHistoryRecord(record)) {', app)
        self.assertIn('return "Recorded on Mantle Sepolia";', app)
        self.assertIn('return "Not recorded on-chain";', app)
        self.assertIn("if (isLiveHistoryRecord(record)) return false;", app)
        self.assertIn('<MonitorField label="Proof type" value={recordReplayProofLabel(record, viewModel, currentAssessmentId, currentProofRecordId)} />', app)

    def test_assessment_hash_does_not_imply_wallet_safety(self) -> None:
        source = VIEW_MODEL_SOURCE.read_text(encoding="utf-8")
        copy = COPY_SOURCE.read_text(encoding="utf-8")

        self.assertIn("This proves the assessment hash, not wallet safety.", source)
        self.assertIn("Assessment hash proves this assessment record, not wallet safety.", copy)

    def test_quiet_wallet_not_safe_unless_coverage_sufficient(self) -> None:
        source = VIEW_MODEL_SOURCE.read_text(encoding="utf-8")

        self.assertIn('if (isPartialOrUnknown(assessment.dataStatus)', source)
        self.assertIn('return "coverage_limited_unknown";', source)
        self.assertIn('return "low_risk_with_sufficient_coverage";', source)
        self.assertNotIn('if (!signals.length) return "low_risk_with_sufficient_coverage";', source)

    def test_pages_read_from_assessment_view_model(self) -> None:
        app = APP_SOURCE.read_text(encoding="utf-8")

        self.assertIn("const viewModel = buildAssessmentViewModel({ scan: data, providerStatus, commitRecord });", app)
        self.assertIn("viewModel.headline", app)
        self.assertIn("viewModel.scoreDisplay", app)
        self.assertIn("viewModel.proofLabel", app)
        self.assertIn("viewModel?.recordability.label", app)
        self.assertIn("viewModel.currentAssessmentRecordLabel", app)
        self.assertIn("viewModel.proofStatus", app)

    def test_evidence_overview_and_proof_use_same_recordability_status(self) -> None:
        app = APP_SOURCE.read_text(encoding="utf-8")

        self.assertIn("recordAssessmentCtaLabel(data, commitRecord, viewModel)", app)
        self.assertIn("const recordability = getRecordability(viewModel)", app)
        self.assertIn("reconciledCommitRecord", app)

    def test_mldt_is_labeled_as_sepolia_test_token(self) -> None:
        app = APP_SOURCE.read_text(encoding="utf-8")
        copy = COPY_SOURCE.read_text(encoding="utf-8")

        self.assertIn("MLDT · Sepolia test token", app)
        self.assertIn("Demo Mantle yield-like token, not official mETH/cmETH.", copy)
        self.assertNotIn("MLDT · Mantle yield asset", app + copy)

    def test_raw_partial_enum_does_not_appear_in_primary_ui(self) -> None:
        app = APP_SOURCE.read_text(encoding="utf-8")
        copy = COPY_SOURCE.read_text(encoding="utf-8")

        self.assertIn('.replaceAll("PARTIAL_OR_UNKNOWN", "Partial scan · unknown fields present")', copy)
        self.assertIn("This is based on a partial scan with unknown fields", app)
        self.assertIn("if (resultKind(data) !== \"coverage_warning_only\") return userFacingCopy(fallback);", app)
        self.assertIn("coverageDisplayLabel", app)
        self.assertNotIn(">PARTIAL_OR_UNKNOWN<", app)

    def test_overview_agent_decision_strip_is_lightweight(self) -> None:
        app = APP_SOURCE.read_text(encoding="utf-8")

        self.assertIn('data-testid="agent-decision-strip"', app)
        self.assertIn("Review transfer evidence", app)
        self.assertIn("Evidence bound", app)
        self.assertIn("inspect evidence, simulate if available, record assessment hash", app)
        self.assertIn("revoke, swap, transfer, auto-sign", app)
        self.assertIn("ready to verify", app)
        self.assertIn("recorded on Mantle", app)


if __name__ == "__main__":
    unittest.main()
