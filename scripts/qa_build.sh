#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../frontend/app"
npm run build
