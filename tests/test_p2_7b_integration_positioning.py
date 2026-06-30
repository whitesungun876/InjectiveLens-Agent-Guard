from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = ROOT / "frontend/app/src/App.tsx"
README = ROOT / "README.md"
DOC = ROOT / "docs/P2_7B_INTEGRATION_POSITIONING.md"
COPY_SOURCE = ROOT / "frontend/app/src/presentation/assessmentCopy.ts"


class P27BIntegrationPositioningTest(unittest.TestCase):
    def test_advanced_includes_three_integration_use_cases(self) -> None:
        app = APP_SOURCE.read_text(encoding="utf-8")

        self.assertIn("function IntegrationLayerPanel", app)
        self.assertIn('data-testid="integration-layer-panel"', app)
        self.assertIn("Integration layer", app)
        self.assertIn("Wallets can call MantleLens before a user signs or interacts", app)
        self.assertIn("Protocols can use MantleLens as a pre-interaction wallet risk check", app)
        self.assertIn("Other agents can call MantleLens through MCP-style tools", app)
        self.assertIn("<IntegrationLayerPanel />", app)

    def test_overview_is_not_heavy_integration_marketing(self) -> None:
        app = APP_SOURCE.read_text(encoding="utf-8")
        summary_start = app.index("function SummaryView")
        summary_end = app.index("function MantleNativeSignalsPanel")
        summary_view = app[summary_start:summary_end]

        self.assertNotIn("Integration layer", summary_view)
        self.assertNotIn("Wallets can call MantleLens", summary_view)
        self.assertNotIn("Protocols can use MantleLens", summary_view)
        self.assertNotIn("Other agents can call MantleLens", summary_view)
        self.assertNotIn("pre-action risk assessment layer", summary_view)

    def test_readme_and_docs_explain_positioning_and_safety_boundaries(self) -> None:
        readme = README.read_text(encoding="utf-8")
        doc = DOC.read_text(encoding="utf-8")

        for text in (readme, doc):
            self.assertIn("Integration Positioning", text)
            self.assertIn("What MantleLens Is", text)
            self.assertIn("What It Is Not", text)
            self.assertIn("Wallets can call MantleLens before a user signs or interacts", text)
            self.assertIn("Protocols can use MantleLens as a pre-interaction wallet risk check", text)
            self.assertIn("Other agents can call MantleLens through MCP-style tools", text)
            self.assertIn("No private key custody", text)
            self.assertIn("No seed phrase handling", text)
            self.assertIn("No automatic wallet connection", text)
            self.assertIn("No automatic transaction broadcast", text)
            self.assertIn("No real revoke/swap/transfer in the default demo path", text)
            self.assertIn("LLM explains", text)
            self.assertIn("Assessment hash proves the assessment record, not wallet safety", text)

    def test_integration_copy_does_not_use_forbidden_claims(self) -> None:
        combined = "\n".join(
            [
                APP_SOURCE.read_text(encoding="utf-8"),
                README.read_text(encoding="utf-8"),
                DOC.read_text(encoding="utf-8"),
            ]
        ).lower()

        for forbidden in (
            "all chains supported",
            "complete multi-chain scanner",
            "guaranteed safe",
            "complete wallet scan",
            "real revoke executed",
            "autonomous trading",
        ):
            self.assertNotIn(forbidden, combined)

    def test_p2_7a_live_proof_copy_remains_intact(self) -> None:
        app = APP_SOURCE.read_text(encoding="utf-8")
        copy = COPY_SOURCE.read_text(encoding="utf-8")

        self.assertIn("Assessment hash submitted. Click Verify assessment to confirm matched.", app)
        self.assertIn("Mantle Sepolia", app)
        self.assertIn("AssessmentRecorded", app)
        self.assertIn("Mantle Sepolia AssessmentLogger", copy)

    def test_previous_b_phase_surfaces_remain_referenced(self) -> None:
        app = APP_SOURCE.read_text(encoding="utf-8")
        copy = COPY_SOURCE.read_text(encoding="utf-8")

        self.assertIn("Missing data is treated as unknown, not safe.", copy)
        self.assertIn("Mantle-native signals", app)
        self.assertIn("Decision Audit", app)


if __name__ == "__main__":
    unittest.main()
