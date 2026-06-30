from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = ROOT / "frontend/app/src/App.tsx"
COPY_SOURCE = ROOT / "frontend/app/src/presentation/assessmentCopy.ts"


class PresentationStateSemanticsTest(unittest.TestCase):
    def test_shared_copy_layer_is_used_across_product_surfaces(self) -> None:
        app = APP_SOURCE.read_text()
        copy = COPY_SOURCE.read_text()

        for helper in (
            "getScoreDisplay",
            "getRiskHeadline",
            "getCoverageLabel",
            "getProofLabel",
            "getRecordStatusLabel",
            "getOutcomeLabel",
            "getSimulationAvailability",
            "getPrimaryNextStep",
            "getSourceStatusGroups",
        ):
            self.assertIn(f"export function {helper}", copy)
            self.assertIn(helper, app)

    def test_partial_live_coverage_is_not_rendered_as_safe_score(self) -> None:
        copy = COPY_SOURCE.read_text()
        app = APP_SOURCE.read_text()

        self.assertIn('value: "Not enough data"', copy)
        self.assertIn("0 detected risk signals · not a safety score", copy)
        self.assertIn("No direct approval, transfer, or yield-risk evidence was found", copy)
        self.assertIn("source coverage is partial, so this wallet cannot be marked safe", copy)
        self.assertIn("scoreDisplayForRecord", app)
        self.assertIn("scoreDisplayForTrendPoint", app)
        self.assertIn('return "Not enough data";', app)

    def test_proof_copy_never_claims_wallet_safety(self) -> None:
        copy = COPY_SOURCE.read_text()
        app = APP_SOURCE.read_text()

        self.assertIn("This proves the assessment hash, not wallet safety.", copy)
        self.assertIn("Assessment hash record is pending. This is not a wallet safety proof.", copy)
        self.assertIn("It proves this assessment record, not wallet safety.", app)
        self.assertIn("Demo replay does not create Mantle transaction proof.", copy)
        self.assertIn('label: "Replay proof only"', copy)
        self.assertIn('label: "Recorded on Mantle"', copy)

    def test_coverage_outcome_record_and_proof_are_separate(self) -> None:
        app = APP_SOURCE.read_text()
        copy = COPY_SOURCE.read_text()

        self.assertIn("Outcome: {recordOutcomeLabel(record, count)} · Coverage: {recordCoverageLabel(record)}", app)
        self.assertIn("Proof: {recordProofStatusLabel(record, viewModel, currentAssessmentId)} · Record status: {recordStatusLabel(record, viewModel, currentAssessmentId)}", app)
        self.assertIn("return copyOutcomeLabel(record, duplicateCount);", app)
        self.assertIn('return "Pending review";', copy)
        self.assertIn('return "Unchanged";', copy)
        self.assertNotIn('return "Risk reduced";', copy)

    def test_simulation_unavailable_has_evidence_reason(self) -> None:
        copy = COPY_SOURCE.read_text()
        app = APP_SOURCE.read_text()

        self.assertIn('label: "Simulation unavailable"', copy)
        self.assertIn("No active approval or yield action found to simulate. Coverage gaps are review-only.", copy)
        self.assertIn("simulationAvailability.reason", app)
        self.assertNotIn("generic “simulate safer choices”", app)

    def test_raw_enums_are_mapped_to_product_language(self) -> None:
        copy = COPY_SOURCE.read_text()
        app = APP_SOURCE.read_text()

        self.assertIn('.replaceAll("PARTIAL_OR_UNKNOWN", "Partial scan · unknown fields present")', copy)
        self.assertIn('.replaceAll("REPLAY_ONLY", "Replay proof only")', copy)
        self.assertIn('.replaceAll("SOURCE_COVERAGE_WARNING", "Source coverage warning")', copy)
        self.assertIn('.replaceAll("rule:rwa_yield_exposure", "Rule-based yield exposure check")', copy)
        self.assertIn('.replaceAll("RwaYieldExposure", "Yield exposure data")', copy)
        self.assertIn('.replaceAll("local_recorded", "Local fallback record")', copy)
        self.assertIn("normalizeUserFacingLabel(String(value || \"\"))", app)
        self.assertIn("enhancementFallbackLabel", app)
        self.assertIn("Raw developer trace", app)

    def test_source_coverage_groups_are_capability_aware(self) -> None:
        copy = COPY_SOURCE.read_text()
        app = APP_SOURCE.read_text()

        self.assertIn("SourceCapabilityStatus", copy)
        self.assertIn("Moralis balances", copy)
        self.assertIn("Moralis wallet history", copy)
        self.assertIn('statusHeadline: "Comparable with caution"', copy)
        self.assertIn("Missing indexed data may hide older approvals, unknown tokens, or transfer history.", copy)
        self.assertIn("<SourceStatusGroupsView groups={groups} />", app)
        self.assertNotIn("Stable enough for comparison", app)


if __name__ == "__main__":
    unittest.main()
