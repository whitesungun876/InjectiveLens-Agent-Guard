#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

python3 - <<'PY'
from backend.mantlelens.workflows import WalletGuardRunner

expected = {
    "stable_wallet": ("Low", "SAFE", "NO_ACTION"),
    "elevated_wallet": ("High", "REVIEW_APPROVAL", "SIMULATE_REVOKE_APPROVAL"),
    "critical_wallet": ("Critical", "PAUSE", "REVIEW_APPROVAL"),
}

for fixture_id, expected_tuple in expected.items():
    package = WalletGuardRunner().scan_wallet(fixture_id=fixture_id, include_explanation=False)
    assessment = package["assessment"]
    actual = (
        assessment["riskLevel"],
        assessment["decisionType"],
        assessment["actionType"],
    )
    if actual != expected_tuple:
        raise SystemExit(f"{fixture_id}: expected {expected_tuple}, got {actual}")
    print(f"{fixture_id}: {' / '.join(actual)}")
PY
