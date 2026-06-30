#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

python3 - <<'PY'
import json
import os
import threading
import time
from urllib import request

from backend.mantlelens.server import create_server

wallet = os.getenv("LIVE_SMOKE_WALLET_ADDRESS", "0x1234567890abcdef1234567890abcdef12345678")
server = create_server("127.0.0.1", 0, quiet=True)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
opener = request.build_opener(request.ProxyHandler({}))

try:
    host, port = server.server_address
    base = f"http://{host}:{port}"
    started = time.perf_counter()
    scan_req = request.Request(
        f"{base}/api/wallet/scan",
        data=json.dumps(
            {
                "dataMode": "live",
                "walletAddress": wallet,
                "includeExplanation": False,
                "historyOptions": {"pageSize": 10, "maxPages": 1, "fromBlock": 1, "toBlock": "latest", "sort": "desc"},
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with opener.open(scan_req, timeout=25) as response:
        scan = json.loads(response.read().decode("utf-8"))

    assessment = scan["assessment"]
    integrity = scan["integrity"]
    evidence_ids = {item["evidenceId"] for item in scan["evidenceBundle"]["evidence"]}
    for risk in assessment["topRisks"]:
        if not risk.get("evidenceIds"):
            raise SystemExit(f"risk without evidenceIds: {risk.get('riskId')}")
        missing = set(risk["evidenceIds"]) - evidence_ids
        if missing:
            raise SystemExit(f"risk evidence missing from bundle: {risk.get('riskId')} {sorted(missing)}")
    if integrity["evidenceBinding"]["status"] != "pass":
        raise SystemExit("evidence binding did not pass")
    if integrity["sourceIntegrity"]["missingDataIsSafe"]:
        raise SystemExit("missing indexed data was marked safe")

    commit_req = request.Request(
        f"{base}/api/assessment/commit",
        data=json.dumps(
            {
                "assessment": assessment,
                "recordMode": "local_only",
                "confirmationReceived": True,
                "idempotencyKey": "idem_p2_http_smoke_" + assessment["assessmentHash"],
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with opener.open(commit_req, timeout=10) as response:
        commit = json.loads(response.read().decode("utf-8"))
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)

record = commit["record"]
if record["commitMode"] != "local_only" or record["onchainWriteAttempted"]:
    raise SystemExit("P2 smoke local commit attempted on-chain write")

duration = time.perf_counter() - started
print(
    json.dumps(
        {
            "durationSec": round(duration, 2),
            "dataMode": assessment["dataMode"],
            "dataStatus": assessment["dataStatus"],
            "evidenceBinding": integrity["evidenceBinding"]["status"],
            "sourceIntegrity": integrity["sourceIntegrity"]["status"],
            "commitMode": record["commitMode"],
            "onchainWriteAttempted": record["onchainWriteAttempted"],
        },
        sort_keys=True,
    )
)
PY
