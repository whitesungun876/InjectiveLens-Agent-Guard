from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = ROOT / "frontend/app/src/App.tsx"
COPY_SOURCE = ROOT / "frontend/app/src/presentation/assessmentCopy.ts"


class P27BMantleNativeSignalsTest(unittest.TestCase):
    def test_mldt_is_labeled_as_demo_yield_like_not_official_meth_cmeth(self) -> None:
        app = APP_SOURCE.read_text(encoding="utf-8")
        copy = COPY_SOURCE.read_text(encoding="utf-8")

        self.assertIn("isDemoMantleYieldLikeToken", copy)
        self.assertIn("Demo Mantle yield-like token", copy)
        self.assertIn("Demo Mantle yield-like token, not official mETH/cmETH.", copy)
        self.assertIn("MLDT · Sepolia test token", app)
        self.assertNotIn("MLDT is official", app)
        self.assertNotIn("MLDT · Mantle yield asset", app)
        self.assertNotIn("MLDT · official mETH/cmETH", app)

    def test_mantle_proof_copy_uses_sepolia_chain_id_and_assessment_logger(self) -> None:
        app = APP_SOURCE.read_text(encoding="utf-8")
        copy = COPY_SOURCE.read_text(encoding="utf-8")

        self.assertIn("getMantleProofNetworkLabel", copy)
        self.assertIn("Mantle Sepolia · chainId 5003", copy)
        self.assertIn("Mantle Sepolia AssessmentLogger", copy)
        self.assertIn("getMantleProofNetworkLabel(data.assessment.chainId)", app)
        self.assertIn("getMantleProofSourceLabel(data.assessment.chainId)", app)
        self.assertIn("AssessmentRecorded", app)

    def test_mantle_explorer_links_remain_part_of_proof_surface(self) -> None:
        app = APP_SOURCE.read_text(encoding="utf-8")

        self.assertIn("logger.explorerBaseUrl", app)
        self.assertIn("txUrl", app)
        self.assertIn("contractUrl", app)
        self.assertIn("Mantle explorer links enabled", app)

    def test_unknown_protocol_labels_are_not_marked_safe(self) -> None:
        copy = COPY_SOURCE.read_text(encoding="utf-8")
        app = APP_SOURCE.read_text(encoding="utf-8")

        self.assertIn("Unknown protocol labels remain unknown, not safe.", copy)
        self.assertIn("Unknown protocol labels remain unknown, not safe.", app)
        self.assertNotIn("unknown protocol is safe", app.lower())
        self.assertNotIn("unknown protocol is safe", copy.lower())

    def test_meth_cmeth_are_not_presented_as_rwa(self) -> None:
        app = APP_SOURCE.read_text(encoding="utf-8")
        copy = COPY_SOURCE.read_text(encoding="utf-8")

        self.assertIn("Mantle yield asset context; not RWA and not investment advice.", copy)
        self.assertIn("mETH and cmETH can create concentrated Mantle yield exposure", app)
        self.assertNotIn("mETH is RWA", app)
        self.assertNotIn("cmETH is RWA", app)
        self.assertNotIn("official RWA", app)

    def test_mantle_native_panel_is_existing_surface_not_new_top_level_page(self) -> None:
        app = APP_SOURCE.read_text(encoding="utf-8")

        self.assertIn('data-testid="mantle-native-signals"', app)
        self.assertIn("Mantle-native signals", app)
        self.assertIn("Mantle Mainnet · 5000 · Coming soon", app)
        self.assertIn("Mantle-first EVM risk engine", app)
        self.assertNotIn("All chains supported", app)
        self.assertNotIn("complete multi-chain scanner", app)
        self.assertNotIn("guaranteed safety", app.lower())


if __name__ == "__main__":
    unittest.main()
