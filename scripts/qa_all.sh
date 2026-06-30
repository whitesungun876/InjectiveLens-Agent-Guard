#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

./scripts/qa_lint.sh
./scripts/qa_typecheck.sh
./scripts/qa_unit.sh
./scripts/qa_integration.sh
./scripts/qa_build.sh
./scripts/qa_replay_smoke.sh
./scripts/qa_p2_smoke.sh
./scripts/qa_provider_config_smoke.sh
./scripts/qa_live_smoke.sh
./scripts/qa_browser_smoke.sh
./scripts/qa_p2_final_demo_smoke.sh
./scripts/qa_p2_6_judge_browser_smoke.sh

echo "mantlelens qa all ok"
