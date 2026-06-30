#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

python3 - <<'PY'
import json
import os
import threading
import time
from urllib import request

from backend.mantlelens.server import create_server

os.environ["LIVE_REQUEST_TIMEOUT_SEC"] = "2"
os.environ["LIVE_REQUEST_RETRIES"] = "0"
os.environ["LIVE_SCAN_DEADLINE_SEC"] = "15"
os.environ["MORALIS_DATA_API_ENABLED"] = "false"
os.environ["MORALIS_BALANCES_ENABLED"] = "false"
os.environ["MORALIS_HISTORY_ENABLED"] = "false"
os.environ["ETHERSCAN_V2_API_KEY"] = ""
os.environ["MANTLESCAN_API_KEY"] = ""

server = create_server("127.0.0.1", 0, quiet=True)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
opener = request.build_opener(request.ProxyHandler({}))

try:
    host, port = server.server_address
    started = time.perf_counter()
    req = request.Request(
        f"http://{host}:{port}/api/wallet/scan",
        data=json.dumps(
            {
                "dataMode": "live",
                "walletAddress": "0x1234567890abcdef1234567890abcdef12345678",
                "includeExplanation": False,
                "historyOptions": {"pageSize": 10, "maxPages": 1},
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with opener.open(req, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)

duration = time.perf_counter() - started
assessment = payload["assessment"]
coverage = payload["coverage"]
statuses = {
    item["status"]
    for item in coverage["sourceAvailability"].values()
    if isinstance(item, dict) and "status" in item
}

if duration >= 15:
    raise SystemExit(f"live scan exceeded 15s: {duration:.2f}s")
if assessment["dataMode"] != "live":
    raise SystemExit("live scan did not return dataMode=live")
if not statuses.issubset({"available", "partial", "unavailable"}):
    raise SystemExit(f"invalid sourceAvailability statuses: {statuses}")

print(f"live smoke ok: {duration:.2f}s {assessment['dataStatus']} {sorted(statuses)}")
PY
