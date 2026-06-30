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
import os

from backend.mantlelens.config import MantleLensConfig

cfg = MantleLensConfig.from_env()
snapshot = cfg.source_snapshot()
checks = {
    "mantleRpc": bool(cfg.effective_rpc_url),
    "moralis": bool(cfg.moralis_api_key and cfg.moralis_data_available),
    "etherscanV2_or_mantlescan": bool(cfg.etherscan_v2_api_key),
    "goPlus": bool(cfg.goplus_api_key),
    "assessmentLogger": bool(cfg.assessment_contract_address and cfg.wallet_private_key),
    "txSimulation": bool(cfg.tx_simulation_rpc_url),
}

print("provider config smoke:")
for name, ok in checks.items():
    print(f"- {name}: {'configured' if ok else 'missing_or_disabled'}")

if not {source.get("status") for source in snapshot.values()}.issubset({"available", "partial", "unavailable"}):
    raise SystemExit("source snapshot contains an invalid status")

if os.getenv("REQUIRE_FULL_P1", "").strip().lower() in {"1", "true", "yes", "on"}:
    missing = [name for name, ok in checks.items() if not ok]
    if missing:
        raise SystemExit("full P1 provider config missing: " + ", ".join(missing))
    print("full P1 provider config ok")
else:
    print("conditional provider config ok")
PY
