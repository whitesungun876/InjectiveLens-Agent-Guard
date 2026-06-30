#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

PORT="${PORT:-8765}"
HOST="${HOST:-127.0.0.1}"
PID_FILE="/tmp/injectivelens_demo_server.pid"
LOG_FILE="/tmp/injectivelens_demo_server.log"

if lsof -tiTCP:"$PORT" -sTCP:LISTEN >/tmp/mantlelens_existing_pids 2>/dev/null; then
  xargs kill </tmp/mantlelens_existing_pids
  sleep 0.3
fi

python3 - <<PY
import subprocess
import sys

log = open("$LOG_FILE", "wb")
proc = subprocess.Popen(
    [sys.executable, "-m", "backend.injectivelens.server", "--host", "$HOST", "--port", "$PORT", "--quiet"],
    cwd="$(pwd)",
    stdin=subprocess.DEVNULL,
    stdout=log,
    stderr=subprocess.STDOUT,
    start_new_session=True,
)
open("$PID_FILE", "w").write(str(proc.pid))
print(proc.pid)
PY

sleep 0.8
curl --noproxy '*' -fsS "http://$HOST:$PORT/api/health" >/dev/null

echo "InjectiveLens Day 3 API is running at http://$HOST:$PORT"
echo "PID: $(cat "$PID_FILE")"
echo "Log: $LOG_FILE"
