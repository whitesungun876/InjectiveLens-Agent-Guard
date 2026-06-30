#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

./scripts/run_demo.sh >/dev/null
./scripts/run_app.sh >/dev/null

curl --noproxy '*' -fsS "http://127.0.0.1:8765/api/health" >/dev/null
curl --noproxy '*' -fsS "http://127.0.0.1:5173/" >/dev/null

python3 - <<'PY'
import json
from urllib import request

base = "http://127.0.0.1:8765"
opener = request.build_opener(request.ProxyHandler({}))

with opener.open(f"{base}/api/provider/status", timeout=10) as response:
    status = json.loads(response.read().decode("utf-8"))

if status["chain"]["chainId"] == 5003 and status["chain"]["displayName"] != "Mantle Sepolia · 5003":
    raise SystemExit("provider status did not expose Mantle Sepolia chain metadata")
rendered_status = json.dumps(status, sort_keys=True)
if "PRIVATE_KEY" in rendered_status or "WALLET_PRIVATE_KEY" in rendered_status or "SIGNER_PRIVATE_KEY" in rendered_status:
    raise SystemExit("provider status leaked a secret key field")

req = request.Request(
    f"{base}/api/wallet/scan",
    data=json.dumps({"dataMode": "demo", "fixtureId": "high_risk_wallet", "includeExplanation": False}).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with opener.open(req, timeout=15) as response:
    scan = json.loads(response.read().decode("utf-8"))

integrity = scan["integrity"]
if integrity["detailResolution"]["status"] != "pass":
    raise SystemExit("demo high-risk evidence did not resolve to panel rows")
if not scan["assessment"]["topRisks"]:
    raise SystemExit("demo high-risk scan returned no top risks")
if "scoreBreakdown" not in scan["assessment"]:
    raise SystemExit("demo high-risk scan did not return scoreBreakdown")
if not scan["assessment"].get("riskEngine", {}).get("allRisks"):
    raise SystemExit("demo high-risk scan did not return riskEngine allRisks")

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
        raise SystemExit(f"risk without evidence ids: {risk.get('riskId')}")
    for evidence_id in risk["evidenceIds"]:
        evidence_type = evidence_by_id[evidence_id]["type"]
        if evidence_type == "balance" and evidence_id not in inventory_ids:
            raise SystemExit(f"balance evidence missing from inventory panel data: {evidence_id}")
        if evidence_type == "approval" and evidence_id not in approval_ids:
            raise SystemExit(f"approval evidence missing from approval panel data: {evidence_id}")
        if evidence_type == "transfer" and evidence_id not in transfer_ids:
            raise SystemExit(f"transfer evidence missing from transfer panel data: {evidence_id}")

print(f"browser smoke prerequisites ok: {status['chain']['displayName']} {len(scan['assessment']['topRisks'])} top risks")
PY
