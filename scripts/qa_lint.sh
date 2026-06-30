#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

python3 -m compileall -q backend tests

python3 - <<'PY'
from pathlib import Path

checks = [
    ("backend/mantlelens", "mock_tx_"),
    ("backend/mantlelens", "mock_outcome_"),
    ("backend/mantlelens", "guaranteed safe"),
    ("frontend/app/src", "guaranteed safe"),
]

violations = []
for root, needle in checks:
    for path in Path(root).rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in {".py", ".ts", ".tsx", ".js", ".css"}:
            continue
        text = path.read_text(errors="ignore")
        if needle in text:
            violations.append(f"{path}: contains {needle!r}")

if violations:
    raise SystemExit("\n".join(violations))

print("lint ok")
PY
