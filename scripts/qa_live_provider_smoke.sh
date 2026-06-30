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

from backend.mantlelens.config import MantleLensConfig
from backend.mantlelens.server import create_server

cfg = MantleLensConfig.from_env()
missing = []
if not cfg.effective_rpc_url:
    missing.append("MANTLE_RPC_URL")
if not cfg.etherscan_v2_api_key:
    missing.append("ETHERSCAN_V2_API_KEY or MANTLESCAN_API_KEY")
if not cfg.goplus_api_key:
    missing.append("GOPLUS_API_KEY")
if not cfg.moralis_api_key:
    missing.append("MORALIS_API_KEY")
if missing:
    raise SystemExit("live provider smoke missing config: " + ", ".join(missing))

wallet = os.getenv("LIVE_SMOKE_WALLET_ADDRESS", "0x1234567890abcdef1234567890abcdef12345678")
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
                "walletAddress": wallet,
                "includeExplanation": False,
                "historyOptions": {"pageSize": 10, "maxPages": 1, "fromBlock": 1, "toBlock": "latest", "sort": "desc"},
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with opener.open(req, timeout=25) as response:
        payload = json.loads(response.read().decode("utf-8"))
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)

duration = time.perf_counter() - started
assessment = payload["assessment"]
coverage = payload["coverage"]
sources = coverage["sourceAvailability"]
required_sources = ["mantleRpc", "etherscanV2", "goPlus", "moralis"]
invalid = {
    name: sources.get(name, {}).get("status")
    for name in required_sources
    if sources.get(name, {}).get("status") not in {"available", "partial"}
}
if invalid:
    raise SystemExit(f"live provider smoke source unavailable: {invalid}")
if duration >= 15:
    raise SystemExit(f"live provider smoke exceeded 15s: {duration:.2f}s")

summary = {
    "durationSec": round(duration, 2),
    "dataMode": assessment["dataMode"],
    "dataStatus": assessment["dataStatus"],
    "riskLevel": assessment["riskLevel"],
    "sourceAvailability": {name: sources.get(name, {}).get("status") for name in required_sources},
    "evidenceCount": payload["evidenceBundle"]["evidenceCount"],
}
print(json.dumps(summary, sort_keys=True))
PY
