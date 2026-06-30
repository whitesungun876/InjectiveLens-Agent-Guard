#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../frontend/app"

PORT="${APP_PORT:-5173}"
HOST="${APP_HOST:-127.0.0.1}"
PID_FILE="/tmp/injectivelens_app_server.pid"
LOG_FILE="/tmp/injectivelens_app_server.log"

if lsof -tiTCP:"$PORT" -sTCP:LISTEN >/tmp/mantlelens_app_existing_pids 2>/dev/null; then
  xargs kill </tmp/mantlelens_app_existing_pids
  sleep 0.3
fi

npm run build >"$LOG_FILE" 2>&1

python3 - <<PY
import subprocess
import sys

log = open("$LOG_FILE", "ab")
proc = subprocess.Popen(
    [sys.executable, "-m", "http.server", "$PORT", "--bind", "$HOST", "--directory", "dist"],
    cwd="$(pwd)",
    stdin=subprocess.DEVNULL,
    stdout=log,
    stderr=subprocess.STDOUT,
    start_new_session=True,
)
open("$PID_FILE", "w").write(str(proc.pid))
print(proc.pid)
PY

sleep 1.0
curl --noproxy '*' -fsS "http://$HOST:$PORT" >/dev/null

echo "InjectiveLens React app is running at http://$HOST:$PORT"
echo "PID: $(cat "$PID_FILE")"
echo "Log: $LOG_FILE"
