from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = ROOT / "frontend/app/src/App.tsx"
COPY_SOURCE = ROOT / "frontend/app/src/presentation/assessmentCopy.ts"
JUDGE_SMOKE_SCRIPT = ROOT / "scripts/qa_p2_6_judge_browser_smoke.sh"
QA_ALL_SCRIPT = ROOT / "scripts/qa_all.sh"
JUDGE_RUNBOOK = ROOT / "docs/P2_6_JUDGE_DEMO_READINESS.md"
P26_DOC = ROOT / "docs/P2_6_DEMO_UX_SIMPLIFICATION.md"


class P26DemoUxSimplificationTest(unittest.TestCase):
    def test_frontend_uses_judge_facing_information_architecture(self) -> None:
        source = APP_SOURCE.read_text()

        for label in ("Overview", "Evidence", "History"):
            self.assertIn(f'label="{label}"', source)
        for label in ("Summary", "Monitor", "On-chain Proof", "Advanced"):
            self.assertNotIn(f'label="{label}"', source)
        self.assertNotIn('data-testid="view-proof-secondary"', source)
        self.assertIn('"overview-view-proof"', source)
        self.assertIn('"evidence-view-proof"', source)
        self.assertIn('"history-all-record-proof"', source)
        self.assertIn('data-testid="open-advanced"', source)
        self.assertIn('secondaryPanel === "advanced" ? "Hide audit" : "Audit"', source)

        self.assertIn("AssessmentHero", source)
        self.assertIn("3 suspicious on-chain signals detected", source)
        self.assertIn("MantleLens Wallet Guard", source)
        self.assertIn("AI on-chain risk intelligence for Mantle wallets.", source)
        self.assertIn("AgentRunTimeline", source)
        self.assertIn("Core on-chain signals", source)
        self.assertIn("P1 enhancement modules", source)
        self.assertIn("Agent identity / ERC-8004 / MCP", source)

    def test_p2_polish_reduces_history_and_evidence_noise(self) -> None:
        source = APP_SOURCE.read_text()

        self.assertIn("showing latest / previous / last changed", source)
        self.assertIn("View complete assessment list", source)
        self.assertIn("Proof contract", source)
        self.assertIn("Source coverage:", source)
        self.assertIn("single-signal-grid", source)
        self.assertIn("View {items.length} evidence item", source)
        self.assertIn("High severity is caused by evidence floor, not raw numeric score alone.", source)
        self.assertIn("Mantle Sepolia proof + MLDT Sepolia test token + chainId 5003 + AssessmentLogger.", source)

    def test_primary_copy_hides_debug_labels(self) -> None:
        source = APP_SOURCE.read_text()
        copy = COPY_SOURCE.read_text()

        self.assertNotIn("Record locally", source)
        self.assertIn("Record assessment hash", source)
        self.assertIn("Ready to record assessment hash", copy)
        self.assertNotIn("On-chain Record", source)
        self.assertIn("On-chain Proof", source)
        self.assertIn("Verify proof", source)
        self.assertIn("Not available in this scan", source)
        self.assertIn("Some indexed sources were unavailable or incomplete.", copy)
        self.assertIn("Comparable with caution", copy)
        self.assertIn("Missing data is treated as unknown, not safe.", copy)
        self.assertIn("Replay fixture /", source)
        self.assertIn("Read call · no tx hash", source)
        self.assertNotIn("Fixture tx reference", source)
        self.assertNotIn("Fixture approval reference", source)

    def test_no_execution_or_wallet_broadcast_copy_regressed(self) -> None:
        source = APP_SOURCE.read_text()

        self.assertNotIn("Send to wallet", source)
        self.assertIn("does not revoke, swap, trade, or sign wallet actions", source)
        self.assertIn("prepareAssessmentCommitCalldata", source)
        self.assertIn("Confirm the AssessmentLogger transaction in your wallet", source)
        self.assertIn("eth_requestAccounts", source)
        self.assertIn("eth_sendTransaction", source)
        self.assertNotIn("eth_sendRawTransaction", source)
        self.assertIn("window.confirm", source)
        self.assertIn("wallet execution disabled", source)
        self.assertIn("Only ERC20 approve(address,uint256) revoke calldata is allowed.", source)
        self.assertNotIn("PRIVATE_KEY", source)
        self.assertNotIn("WALLET_PRIVATE_KEY", source)
        self.assertNotIn("SIGNER_PRIVATE_KEY", source)

    def test_live_labels_are_explicit(self) -> None:
        source = APP_SOURCE.read_text()

        self.assertIn("Demo scenario · ${defaultTarget?.name || \"Mantle Sepolia\"}-compatible data", source)
        self.assertIn("Live ${networkName(assessment.chainId)} · read-only · ${assessment.chainId}", source)

    def test_scan_controls_use_single_demo_data_target(self) -> None:
        source = APP_SOURCE.read_text()

        self.assertIn("Scan mode", source)
        self.assertIn("Demo scenario", source)
        self.assertIn("Live scan", source)
        self.assertIn("Scan wallet", source)
        self.assertIn("Demo data · Mantle risk profile", source)
        self.assertIn("Run demo scan", source)
        self.assertNotIn("Scan demo wallet", source)
        self.assertNotIn("Demo replay uses the selected scenario", source)
        self.assertNotIn("Sample:", source)
        self.assertIn("Choose a scenario, then run the demo scan to generate that result.", source)
        self.assertIn("Read-only scan. No wallet signing, revoke, swap, transfer, or transaction broadcast.", source)
        self.assertIn("Enter public 0x wallet address", source)
        self.assertNotIn("Load Sepolia proof sample", source)
        self.assertIn("Use Sepolia sample wallet", source)
        self.assertIn("Enter a valid 0x address to run a Mantle Sepolia read-only scan.", source)

    def test_benchmark_case_selector_is_judge_ready(self) -> None:
        source = APP_SOURCE.read_text()

        self.assertIn("Demo scenario", source)
        for label in (
            "Multi-signal wallet",
            "Approval anomaly",
            "Address poisoning signal",
            "Yield concentration signal",
            "Partial source coverage",
            "Quiet wallet",
            "Critical red-flag wallet",
        ):
            self.assertIn(label, source)
        for fixture in (
            "high_risk_wallet",
            "elevated_wallet",
            "address_poisoning_wallet",
            "yield_concentration_wallet",
            "moderate_partial_wallet",
            "quiet_wallet",
            "critical_wallet",
        ):
            self.assertIn(f'fixtureId: "{fixture}"', source)
        self.assertIn("Replay benchmark only; use live Sepolia for a Mantlescan tx proof.", source)
        self.assertIn("The wallet itself has little activity, so the scan cannot infer enough behavior to call it safe.", source)
        self.assertIn("Multiple high-risk signals in one wallet task, but no hard red-flag block.", source)
        self.assertIn("Portfolio exposure signal for mETH/cmETH concentration, not a scam or attack signal.", source)
        self.assertIn("PAUSE and review approval", source)
        self.assertIn("selectedBenchmarkCase.fixtureId", source)

    def test_judge_demo_readiness_controls_are_visible(self) -> None:
        source = APP_SOURCE.read_text()
        copy = COPY_SOURCE.read_text()

        self.assertNotIn("Load Sepolia proof sample", source)
        self.assertIn("Use Sepolia sample wallet", source)
        self.assertIn("Benchmark case matrix", source)
        self.assertIn("Run benchmark suite", source)
        self.assertIn("benchmarkCaseId", source)
        self.assertIn("benchmarkCaseLabel", source)
        self.assertIn("Ready to record assessment hash", copy)
        self.assertIn("agent-trace-section", source)
        self.assertIn("scrollIntoView", source)
        self.assertIn("Compatible registration · local feedback in demo", source)
        self.assertIn("local reputation feedback in demo", source)
        self.assertIn("No identity NFT is claimed unless a contract address and token id are shown.", source)
        self.assertNotIn("Feedback-ready", source)
        self.assertIn("The risk model selected this action because", source)
        self.assertIn("Formula: weighted score = sum(metric score x weight).", source)
        self.assertIn("scoreBreakdownDisplayMetrics", source)
        self.assertIn('className="case-chip"', source)

    def test_live_scan_uses_scan_target_abstraction(self) -> None:
        source = APP_SOURCE.read_text()

        self.assertIn("Scan mode", source)
        self.assertIn("Mantle Sepolia · Testnet · 5003", source)
        self.assertIn("Mantle Mainnet", source)
        self.assertIn("Custom EVM network", source)
        self.assertIn("Adapter-ready / Coming soon", source)
        self.assertIn("targetId: demo ? undefined : target?.id", source)
        self.assertIn("chainId: demo ? undefined : target?.chainId", source)
        self.assertIn("Review a Mantle wallet before acting.", source)
        self.assertNotIn("<small>Network</small>", source)

    def test_scan_derived_data_is_not_loaded_before_user_scans(self) -> None:
        source = APP_SOURCE.read_text()

        self.assertNotIn("useEffect(() => {\n    handleScan();\n  }, []);", source)
        self.assertIn("function PreScanSummary", source)
        self.assertIn("No wallet scanned yet.", source)
        self.assertIn("Run a demo scenario or live read-only scan to generate approval, transfer, yield, and source-coverage risk signals.", source)
        self.assertIn("No wallet scanned yet.", source)
        self.assertIn("No revoke, swap, transfer, or wallet signing happens unless a user explicitly confirms a separate on-chain proof action.", source)

    def test_summary_uses_alpha_data_signal_language(self) -> None:
        source = APP_SOURCE.read_text()
        copy = COPY_SOURCE.read_text()

        self.assertIn("Approval anomaly", source)
        self.assertIn("Address poisoning signal", source)
        self.assertIn("Yield concentration signal", source)
        self.assertIn("Signal Risk Index", copy)
        self.assertIn("Next step", source)
        self.assertIn("assessmentDecisionLabel", source)
        self.assertIn("roundedScore", source)
        self.assertIn("Assessment history & risk trend", source)
        self.assertIn("Simulated action: revoke unlimited USDT approval", source)
        self.assertNotIn("High wallet risk", source)
        self.assertNotIn("59.75 score", source)
        self.assertNotIn("transaction created {String(simulation.transactionCreated)}", source)

    def test_judge_browser_smoke_is_wired_into_final_qa(self) -> None:
        script = JUDGE_SMOKE_SCRIPT.read_text()
        qa_all = QA_ALL_SCRIPT.read_text()

        self.assertIn("playwright", script)
        self.assertIn("MantleLens Wallet Guard", script)
        self.assertIn("Overview\\nEvidence\\nHistory", script)
        self.assertIn("scanConsoleHeight > 520", script)
        self.assertIn("caseMetaHeight > 90", script)
        self.assertIn("The risk model selected this action because", script)
        self.assertIn("View replay proof", script)
        self.assertIn("Expand supporting records", script)
        self.assertIn("Evidence reviewed", script)
        self.assertIn("Replay fixture /", script)
        self.assertIn("Read call · no tx hash", script)
        self.assertIn("ERC-8004-compatible registration", script)
        self.assertIn("No identity NFT is claimed unless a contract address and token id are shown.", script)
        self.assertIn("Formula: weighted score = sum(metric score x weight).", script)
        self.assertIn("p2_6_judge_browser_smoke.png", script)
        self.assertIn("./scripts/qa_p2_6_judge_browser_smoke.sh", qa_all)

    def test_judge_runbook_matches_current_navigation_and_safety_boundaries(self) -> None:
        runbook = JUDGE_RUNBOOK.read_text()
        p26_doc = P26_DOC.read_text()

        self.assertIn("autonomous agent gathers on-chain data", runbook)
        self.assertIn("Replay only", runbook)
        self.assertIn("Live Proof Path", runbook)
        self.assertIn("A real on-chain commit requires an explicit user action and confirmation.", runbook)
        self.assertIn("Target 11 Acceptance", runbook)
        self.assertIn("Target 12 Acceptance", runbook)
        self.assertIn("No test sends an on-chain transaction.", runbook)
        self.assertIn("Overview", p26_doc)
        self.assertIn("Evidence", p26_doc)
        self.assertIn("History", p26_doc)
        self.assertNotIn("`Monitor`", p26_doc)


if __name__ == "__main__":
    unittest.main()
