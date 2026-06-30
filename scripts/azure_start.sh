#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

export HOST="${HOST:-0.0.0.0}"
export PORT="${PORT:-8000}"
export INJECTIVELENS_STATIC_DIR="${INJECTIVELENS_STATIC_DIR:-$(pwd)/frontend/app/dist}"
export INJECTIVELENS_STATE_FILE="${INJECTIVELENS_STATE_FILE:-/tmp/injectivelens_state.json}"
export INJECTIVE_PROOF_RECORDER_MODE="${INJECTIVE_PROOF_RECORDER_MODE:-external_tx}"

exec python -m backend.injectivelens.server --host "$HOST" --port "$PORT" --quiet
