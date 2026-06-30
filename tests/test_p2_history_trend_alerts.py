from __future__ import annotations

import json
import os
import threading
import unittest
from urllib import request
from unittest.mock import patch

from backend.mantlelens.alerts import InMemoryAlertStore
from backend.mantlelens.hashutil import stable_hash
from backend.mantlelens.history_store import InMemoryAssessmentHistoryStore
from backend.mantlelens.server import create_server


WALLET = "0x1234567890abcdef1234567890abcdef12345678"
WALLET_HASH = stable_hash(WALLET.lower())
EVIDENCE_ID = "ev_high_approval"


class P2HistoryTrendAlertsTest(unittest.TestCase):
    def test_assessment_history_stores_multiple_scans_for_same_wallet(self) -> None:
        store = InMemoryAssessmentHistoryStore()
        first = store.record_scan(**_scan_args("a1", score=40, timestamp="2026-06-09T00:00:00+00:00"))
        second = store.record_scan(**_scan_args("a2", score=65, timestamp="2026-06-09T00:01:00+00:00"))

        records = store.list_records(address=WALLET, chain_id=5003, mode="live", limit=10)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["assessmentId"], second["assessmentId"])
        self.assertEqual(records[1]["assessmentId"], first["assessmentId"])
        self.assertEqual({record["mode"] for record in records}, {"live"})

    def test_history_endpoint_returns_records_ordered_and_mode_scoped(self) -> None:
        store = InMemoryAssessmentHistoryStore()
        store.record_scan(**_scan_args("demo", mode="demo", timestamp="2026-06-09T00:00:00+00:00", score=20, chain_id=5003))
        store.record_scan(**_scan_args("live1", mode="live", timestamp="2026-06-09T00:01:00+00:00", score=30, chain_id=5003))
        store.record_scan(**_scan_args("live2", mode="live", timestamp="2026-06-09T00:02:00+00:00", score=60, chain_id=5003))

        with patch("backend.mantlelens.server.ASSESSMENT_HISTORY_STORE", store):
            payload = _get_json(f"/api/wallet/history?address={WALLET}&chain_id=5003&limit=10")
            mixed = _get_json(f"/api/wallet/history?address={WALLET}&chain_id=5003&mode=all&limit=10")

        self.assertEqual(payload["mode"], "live")
        self.assertEqual(payload["modeSelection"], "latest_mode_without_mixing")
        self.assertEqual([record["assessmentId"] for record in payload["records"]], ["assessment_live2", "assessment_live1"])
        self.assertEqual(mixed["modeSelection"], "explicit_all")
        self.assertEqual(mixed["recordCount"], 3)

    def test_demo_replay_and_live_records_are_clearly_marked(self) -> None:
        store = InMemoryAssessmentHistoryStore()
        store.record_scan(**_scan_args("demo", mode="demo", timestamp="2026-06-09T00:00:00+00:00"))
        store.record_scan(**_scan_args("replay", mode="replay", timestamp="2026-06-09T00:01:00+00:00"))
        store.record_scan(**_scan_args("live", mode="live", timestamp="2026-06-09T00:02:00+00:00"))

        records = store.list_records(address=WALLET, chain_id=5003, mode=None, limit=10)

        self.assertEqual({record["mode"] for record in records}, {"demo", "replay", "live"})
        self.assertTrue(all(record["walletAddress"] == WALLET.lower() for record in records))

    def test_trend_endpoint_insufficient_history_for_one_record(self) -> None:
        store = InMemoryAssessmentHistoryStore()
        store.record_scan(**_scan_args("single", timestamp="2026-06-09T00:00:00+00:00"))

        with patch("backend.mantlelens.server.ASSESSMENT_HISTORY_STORE", store):
            payload = _get_json(f"/api/wallet/trend?address={WALLET}&chain_id=5003&mode=live")

        self.assertEqual(payload["trendStatus"], "insufficient_history")
        self.assertEqual(payload["pointCount"], 1)
        self.assertIn("Need at least two", payload["trendSummary"])

    def test_trend_endpoint_returns_score_deltas_for_multiple_records(self) -> None:
        store = InMemoryAssessmentHistoryStore()
        store.record_scan(**_scan_args("first", score=35, level="Moderate", timestamp="2026-06-09T00:00:00+00:00"))
        store.record_scan(**_scan_args("second", score=55, level="High", timestamp="2026-06-09T00:01:00+00:00"))

        trend = store.trend(address=WALLET, chain_id=5003, mode="live")

        self.assertEqual(trend["trendStatus"], "comparable")
        self.assertEqual(trend["latestScoreDelta"], 20.0)
        self.assertEqual(trend["delta"]["scoreDelta"], 20.0)
        self.assertEqual(trend["latestRiskLevelChange"]["direction"], "worsened")

    def test_trend_does_not_claim_improvement_when_source_coverage_degraded(self) -> None:
        store = InMemoryAssessmentHistoryStore()
        store.record_scan(**_scan_args("first", score=80, level="High", timestamp="2026-06-09T00:00:00+00:00"))
        store.record_scan(
            **_scan_args(
                "second",
                score=20,
                level="Low",
                timestamp="2026-06-09T00:01:00+00:00",
                coverage=_coverage(source_status="unavailable"),
            )
        )

        trend = store.trend(address=WALLET, chain_id=5003, mode="live")

        self.assertEqual(trend["trendStatus"], "partially_comparable")
        self.assertFalse(trend["delta"]["improvementConfirmed"])
        self.assertIn("improvement is not confirmed", trend["trendSummary"])

    def test_new_high_risk_approval_creates_alert_with_resolvable_evidence(self) -> None:
        alert_store = InMemoryAlertStore()
        args = _scan_args("approval")

        alerts = alert_store.evaluate(
            assessment=args["assessment"],
            evidence_bundle=args["evidence_bundle"],
            coverage=args["coverage"],
            inventory=None,
            history=None,
            trend=None,
        )

        approval_alert = next(alert for alert in alerts if alert["alertType"] == "new_active_approval")
        evidence_ids = {item["evidenceId"] for item in args["evidence_bundle"]["evidence"]}
        self.assertTrue(set(approval_alert["evidenceIds"]).issubset(evidence_ids))
        self.assertEqual(approval_alert["type"], "new_active_approval")
        self.assertIn("simulate revoke impact", approval_alert["recommendedSafeActions"])

    def test_risk_score_increase_and_level_worsening_create_alerts(self) -> None:
        store = InMemoryAssessmentHistoryStore()
        alert_store = InMemoryAlertStore()
        store.record_scan(**_scan_args("first", score=20, level="Low", timestamp="2026-06-09T00:00:00+00:00"))
        current = _scan_args("second", score=75, level="High", timestamp="2026-06-09T00:01:00+00:00")
        store.record_scan(**current)

        alerts = alert_store.evaluate(
            assessment=current["assessment"],
            evidence_bundle=current["evidence_bundle"],
            coverage=current["coverage"],
            inventory=None,
            history=None,
            trend=store.trend(address=WALLET, chain_id=5003, mode="live"),
        )
        types = {alert["alertType"] for alert in alerts}

        self.assertIn("risk_score_increased", types)
        self.assertIn("risk_level_increased", types)

    def test_source_failure_creates_alert(self) -> None:
        alert_store = InMemoryAlertStore()
        args = _scan_args("source_failed", coverage=_coverage(source_status="unavailable"))

        alerts = alert_store.evaluate(
            assessment=args["assessment"],
            evidence_bundle=args["evidence_bundle"],
            coverage=args["coverage"],
            inventory=None,
            history=None,
            trend=None,
        )

        self.assertIn("source_unavailable", {alert["alertType"] for alert in alerts})

    def test_duplicate_scans_do_not_spam_duplicate_alerts(self) -> None:
        alert_store = InMemoryAlertStore()
        args = _scan_args("dupe")
        for _ in range(2):
            alert_store.evaluate(
                assessment=args["assessment"],
                evidence_bundle=args["evidence_bundle"],
                coverage=args["coverage"],
                inventory=None,
                history=None,
                trend=None,
            )

        open_alerts = alert_store.list_alerts(wallet_address=WALLET, chain_id=5003, mode="live", status="open")
        approval_alerts = [alert for alert in open_alerts if alert["alertType"] == "new_active_approval"]
        self.assertEqual(len(approval_alerts), 1)
        self.assertEqual(approval_alerts[0]["occurrenceCount"], 2)

    def test_alert_can_be_resolved_and_remains_queryable(self) -> None:
        alert_store = InMemoryAlertStore()
        args = _scan_args("resolve")
        alert = alert_store.evaluate(
            assessment=args["assessment"],
            evidence_bundle=args["evidence_bundle"],
            coverage=args["coverage"],
            inventory=None,
            history=None,
            trend=None,
        )[0]

        resolved = alert_store.resolve(alert_id=alert["alertId"], resolution_note="reviewed")
        resolved_alerts = alert_store.list_alerts(wallet_address=WALLET, chain_id=5003, mode="live", status="resolved")

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["status"], "resolved")
        self.assertEqual(resolved["resolutionNote"], "reviewed")
        self.assertEqual(len(resolved_alerts), 1)

    def test_history_trend_alert_endpoints_do_not_leak_secrets(self) -> None:
        secret = "unit-test-private-key"
        store = InMemoryAssessmentHistoryStore()
        alert_store = InMemoryAlertStore()
        args = _scan_args("redacted")
        store.record_scan(**args)
        alert_store.evaluate(
            assessment=args["assessment"],
            evidence_bundle=args["evidence_bundle"],
            coverage=args["coverage"],
            inventory=None,
            history=None,
            trend=store.trend(address=WALLET, chain_id=5003, mode="live"),
        )

        with patch.dict(os.environ, {"PRIVATE_KEY": secret, "WALLET_PRIVATE_KEY": secret, "SIGNER_PRIVATE_KEY": secret}, clear=False), patch(
            "backend.mantlelens.server.ASSESSMENT_HISTORY_STORE", store
        ), patch("backend.mantlelens.server.ALERT_STORE", alert_store):
            history = _get_json(f"/api/wallet/history?address={WALLET}&chain_id=5003&mode=live")
            trend = _get_json(f"/api/wallet/trend?address={WALLET}&chain_id=5003&mode=live")
            alerts = _get_json(f"/api/alerts?address={WALLET}&chain_id=5003&mode=live&status=all")

        rendered = json.dumps({"history": history, "trend": trend, "alerts": alerts}, sort_keys=True)
        self.assertNotIn(secret, rendered)

    def test_no_test_sends_real_onchain_transaction(self) -> None:
        with patch(
            "backend.mantlelens.onchain.SignedAssessmentTransactionSender.send",
            side_effect=AssertionError("P2.4 tests must not send on-chain transactions"),
        ):
            store = InMemoryAssessmentHistoryStore()
            store.record_scan(**_scan_args("no_tx"))

        self.assertEqual(store.list_records(address=WALLET, chain_id=5003, mode="live", limit=1)[0]["commitTxHash"], None)


def _scan_args(
    suffix: str,
    *,
    score: float = 85,
    level: str = "Critical",
    mode: str = "live",
    chain_id: int = 5003,
    timestamp: str = "2026-06-09T00:00:00+00:00",
    coverage: dict | None = None,
) -> dict:
    assessment = _assessment(suffix, score=score, level=level, mode=mode, chain_id=chain_id, timestamp=timestamp)
    evidence_bundle = {
        "evidenceBundleHash": stable_hash(["bundle", suffix]),
        "evidenceCount": 1,
        "evidence": [
            {
                "evidenceId": EVIDENCE_ID,
                "type": "approval",
                "source": "unit_fixture",
                "claimText": "Unlimited approval evidence.",
                "allowanceConfirmed": True,
            }
        ],
    }
    return {
        "assessment": assessment,
        "evidence_bundle": evidence_bundle,
        "coverage": coverage or _coverage(),
        "inventory": None,
        "history": None,
    }


def _assessment(
    suffix: str,
    *,
    score: float,
    level: str,
    mode: str,
    chain_id: int,
    timestamp: str,
) -> dict:
    risk = {
        "riskId": "risk_high_approval",
        "type": "approval",
        "category": "approval",
        "title": "Active unlimited approval",
        "severity": "High",
        "claimText": "USDT has an active unlimited approval.",
        "scoreImpact": 90,
        "confidence": 0.9,
        "evidenceIds": [EVIDENCE_ID],
    }
    assessment_hash = stable_hash(["assessment", suffix, score, level, mode, timestamp])
    return {
        "assessmentId": f"assessment_{suffix}",
        "timestamp": timestamp,
        "chainId": chain_id,
        "wallet": {"address": WALLET, "walletHash": WALLET_HASH},
        "walletRiskScore": score,
        "riskLevel": level,
        "dataConfidence": 0.82,
        "dataStatus": "PARTIAL_OR_UNKNOWN",
        "dataMode": mode,
        "topRisks": [risk],
        "suggestedActions": [
            {
                "actionId": "act_review",
                "actionType": "REVIEW_APPROVAL",
                "label": "Review spender",
                "executionMode": "view_only",
                "evidenceIds": [EVIDENCE_ID],
            }
        ],
        "assessmentHash": assessment_hash,
        "evidenceBundleHash": stable_hash(["bundle", suffix]),
        "recommendationHash": stable_hash(["recommendation", suffix]),
        "topRisksHash": stable_hash([risk]),
    }


def _coverage(source_status: str = "available") -> dict:
    return {
        "dataStatus": "PARTIAL_OR_UNKNOWN",
        "dataCompleteness": {
            "approvalHistory": source_status,
            "transferHistory": "available",
            "fullTokenInventory": "available",
        },
        "sourceAvailability": {
            "etherscanV2": {"status": source_status, "limitation": None if source_status == "available" else "source unavailable"},
            "mantleRpc": {"status": "available"},
        },
        "missingDataIsSafe": False,
    }


def _get_json(path: str) -> dict:
    server = create_server("127.0.0.1", 0, quiet=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    opener = request.build_opener(request.ProxyHandler({}))
    try:
        host, port = server.server_address
        with opener.open(f"http://{host}:{port}{path}", timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
