#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

./scripts/run_demo.sh >/dev/null
./scripts/run_app.sh >/dev/null

curl --noproxy '*' -fsS "http://127.0.0.1:8765/api/health" >/dev/null
curl --noproxy '*' -fsS "http://127.0.0.1:5173/" >/dev/null

python3 - <<'PY'
import json
import os
from urllib import request


BASE = "http://127.0.0.1:8765"
LIVE_WALLET = os.getenv("LIVE_SMOKE_WALLET_ADDRESS", "").strip()
SECRET_FIELD_MARKERS = ("PRIVATE_KEY", "WALLET_PRIVATE_KEY", "SIGNER_PRIVATE_KEY")


opener = request.build_opener(request.ProxyHandler({}))


def get_json(path: str, timeout: int = 15) -> dict:
    with opener.open(f"{BASE}{path}", timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(path: str, payload: dict, timeout: int = 20) -> dict:
    req = request.Request(
        f"{BASE}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with opener.open(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def assert_no_secret_markers(name: str, payload: dict) -> None:
    rendered = json.dumps(payload, sort_keys=True)
    for marker in SECRET_FIELD_MARKERS:
        if marker in rendered:
            raise SystemExit(f"{name} leaked secret marker {marker}")


def assert_detail_resolution(scan: dict) -> None:
    if scan["integrity"]["detailResolution"]["status"] != "pass":
        raise SystemExit("demo detail evidence did not resolve")
    evidence_by_id = {item["evidenceId"]: item for item in scan["evidenceBundle"]["evidence"]}
    inventory_ids = {
        evidence_id
        for row in scan.get("inventory", {}).get("tokens", [])
        for evidence_id in ([row.get("evidenceId")] + list(row.get("evidenceIds") or []))
        if evidence_id
    }
    approval_ids = {
        evidence_id
        for row in scan.get("history", {}).get("approvalHistory", {}).get("items", [])
        for evidence_id in ([row.get("evidenceId")] + list(row.get("evidenceIds") or []))
        if evidence_id
    }
    transfer_ids = {
        evidence_id
        for row in scan.get("history", {}).get("transferHistory", {}).get("items", [])
        for evidence_id in ([row.get("evidenceId")] + list(row.get("evidenceIds") or []))
        if evidence_id
    }
    for risk in scan["assessment"]["topRisks"]:
        if not risk.get("evidenceIds"):
            raise SystemExit(f"risk without evidenceIds: {risk.get('riskId')}")
        for evidence_id in risk["evidenceIds"]:
            evidence = evidence_by_id.get(evidence_id)
            if not evidence:
                raise SystemExit(f"risk evidence missing from bundle: {evidence_id}")
            evidence_type = evidence["type"]
            if evidence_type == "balance" and evidence_id not in inventory_ids:
                raise SystemExit(f"balance evidence missing from inventory panel data: {evidence_id}")
            if evidence_type == "approval" and evidence_id not in approval_ids:
                raise SystemExit(f"approval evidence missing from approval panel data: {evidence_id}")
            if evidence_type == "transfer" and evidence_id not in transfer_ids:
                raise SystemExit(f"transfer evidence missing from transfer panel data: {evidence_id}")


def assert_no_scan_commit(name: str, scan: dict) -> None:
    if any(event.get("eventType") == "assessment_commit_status_changed" for event in scan.get("trace", {}).get("events", [])):
        raise SystemExit(f"{name} scan unexpectedly triggered assessment commit")


status = get_json("/api/provider/status")
assert_no_secret_markers("provider status", status)
if status.get("chain", {}).get("chainId") == 5003 and status.get("chain", {}).get("displayName") != "Mantle Sepolia · 5003":
    raise SystemExit("provider status chain display is not Mantle Sepolia · 5003")

demo = post_json(
    "/api/wallet/scan",
    {"dataMode": "demo", "fixtureId": "high_risk_wallet", "includeExplanation": False},
    timeout=20,
)
assert_detail_resolution(demo)
assert_no_scan_commit("demo", demo)

benchmark_cases = {
    "multi_signal": ("high_risk_wallet", {"risk_approval_unknown_unlimited", "risk_transfer_address_poisoning", "risk_rwa_yield_exposure"}),
    "approval_anomaly": ("elevated_wallet", {"risk_approval_unknown_unlimited"}),
    "address_poisoning": ("address_poisoning_wallet", {"risk_transfer_address_poisoning"}),
    "yield_concentration": ("yield_concentration_wallet", {"risk_rwa_yield_exposure"}),
    "partial_coverage": ("moderate_partial_wallet", {"risk_source_coverage_partial"}),
    "quiet_wallet": ("quiet_wallet", {"risk_wallet_activity_unknown"}),
    "critical_risk": ("critical_wallet", {"risk_approval_malicious_active"}),
}
benchmark_summary = {}
for case_name, (fixture_id, expected_risks) in benchmark_cases.items():
    case_scan = post_json(
        "/api/wallet/scan",
        {"dataMode": "demo", "fixtureId": fixture_id, "includeExplanation": False},
        timeout=20,
    )
    assert_no_secret_markers(f"benchmark {case_name}", case_scan)
    assert_no_scan_commit(f"benchmark {case_name}", case_scan)
    risk_ids = {risk.get("riskId") or risk.get("risk_id") for risk in case_scan["assessment"]["topRisks"]}
    if not expected_risks.issubset(risk_ids):
        raise SystemExit(f"benchmark {case_name} missing expected risks {sorted(expected_risks - risk_ids)}")
    if any(not risk.get("evidenceIds") for risk in case_scan["assessment"]["topRisks"]):
        raise SystemExit(f"benchmark {case_name} returned a top risk without evidenceIds")
    if case_name == "quiet_wallet":
        if case_scan["assessment"]["dataStatus"] != "PARTIAL_OR_UNKNOWN" or case_scan["assessment"]["decisionType"] == "SAFE":
            raise SystemExit("quiet wallet was not treated as unknown/partial coverage")
    if case_name == "critical_risk":
        if case_scan["assessment"]["riskLevel"] != "Critical" or case_scan["assessment"]["decisionType"] != "PAUSE":
            raise SystemExit("critical benchmark did not produce Critical/PAUSE")
    benchmark_summary[case_name] = {
        "level": case_scan["assessment"]["riskLevel"],
        "decision": case_scan["assessment"]["decisionType"],
        "risks": sorted(risk_ids),
    }

wallet = demo["assessment"]["wallet"]
chain_id = demo["assessment"]["chainId"]
history = get_json(f"/api/wallet/history?walletHash={wallet['walletHash']}&chain_id={chain_id}&mode=demo&limit=10")
trend = get_json(f"/api/wallet/trend?walletHash={wallet['walletHash']}&chain_id={chain_id}&mode=demo&limit=10")
alerts = get_json(f"/api/alerts?walletHash={wallet['walletHash']}&chain_id={chain_id}&mode=demo&status=all")
assert_no_secret_markers("history", history)
assert_no_secret_markers("trend", trend)
assert_no_secret_markers("alerts", alerts)
if history.get("recordCount", 0) < 1:
    raise SystemExit("demo scan did not create a history record")
if not trend.get("trendStatus"):
    raise SystemExit("trend endpoint did not return trendStatus")
if not alerts.get("alerts"):
    raise SystemExit("demo high-risk scan did not create informational alerts")

first_alert = alerts["alerts"][0]
resolved = post_json(f"/api/alerts/{first_alert['alertId']}/resolve", {"resolutionNote": "final demo smoke"})
if resolved.get("alert", {}).get("status") != "resolved":
    raise SystemExit("alert resolve did not return resolved status")

verify = get_json("/api/assessment/commit/verify?tx_hash=0x0000000000000000000000000000000000000000000000000000000000000000", timeout=15)
assert_no_secret_markers("verify", verify)
if verify.get("verificationStatus") not in {"unknown", "pending", "failed", "mismatch"} and verify.get("status") not in {"unknown", "pending", "failed", "mismatch"}:
    raise SystemExit("verify endpoint returned an unexpected status for a nonexistent tx")

live_status = "skipped_no_live_wallet"
if LIVE_WALLET:
    live = post_json(
        "/api/wallet/scan",
        {
            "dataMode": "live",
            "walletAddress": LIVE_WALLET,
            "includeExplanation": False,
            "historyOptions": {"pageSize": 10, "maxPages": 1, "fromBlock": 1, "toBlock": "latest", "sort": "desc"},
        },
        timeout=30,
    )
    assert_no_secret_markers("live scan", live)
    if live["integrity"]["sourceIntegrity"]["missingDataIsSafe"]:
        raise SystemExit("live missing indexed data was treated as safe")
    assert_no_scan_commit("live", live)
    live_status = live["assessment"]["dataStatus"]

print(
    json.dumps(
        {
            "benchmarkCases": sorted(benchmark_summary),
            "demoRisks": len(demo["assessment"]["topRisks"]),
            "historyRecords": history.get("recordCount"),
            "trendStatus": trend.get("trendStatus"),
            "alerts": len(alerts.get("alerts", [])),
            "liveStatus": live_status,
            "verifyStatus": verify.get("verificationStatus") or verify.get("status"),
        },
        sort_keys=True,
    )
)
PY
