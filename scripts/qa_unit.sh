#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

export ASSESSMENT_CONTRACT_ADDRESS=
export ASSESSMENT_LOGGER_ADDRESS=
export PRIVATE_KEY=
export WALLET_PRIVATE_KEY=
export SIGNER_PRIVATE_KEY=

python3 -m unittest discover -s tests -v
