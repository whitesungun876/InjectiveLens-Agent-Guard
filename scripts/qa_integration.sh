#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

export ASSESSMENT_CONTRACT_ADDRESS=
export ASSESSMENT_LOGGER_ADDRESS=
export PRIVATE_KEY=
export WALLET_PRIVATE_KEY=
export SIGNER_PRIVATE_KEY=

python3 -m unittest \
  tests.test_day5_day6_workflows \
  tests.test_day7_day8_simulation_ledger \
  tests.test_day9_day10_protocol_demo \
  tests.test_p1_live_data_foundation \
  tests.test_p2_live_commit_integrity \
  tests.test_p2_preflight_hardening \
  tests.test_p2_risk_engine_hardening \
  tests.test_p2_assessment_readback \
  tests.test_p2_history_trend_alerts \
  tests.test_p2_final_demo_qa \
  tests.test_phase6_phase7_acceptance \
  tests.test_phase9_production_readiness \
  -v
