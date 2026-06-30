#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = [
    ROOT / "contracts" / "AssessmentLogger.sol",
    ROOT / "contracts" / "MantleLensDemoToken.sol",
]
BUILD_DIR = ROOT / "build" / "p2_7_demo"
PUBLIC_ARTIFACT = ROOT / "frontend" / "app" / "public" / "p2_7_demo_contracts.json"


def main() -> None:
    sources = {path.name: {"content": path.read_text(encoding="utf-8")} for path in CONTRACTS}
    standard_input = {
        "language": "Solidity",
        "sources": sources,
        "settings": {
            "optimizer": {"enabled": True, "runs": 200},
            "viaIR": True,
            "outputSelection": {
                "*": {
                    "*": [
                        "abi",
                        "evm.bytecode.object",
                        "evm.methodIdentifiers",
                    ]
                }
            },
        },
    }
    result = subprocess.run(
        ["npx", "--yes", "solc@0.8.20", "--standard-json"],
        input=json.dumps(standard_input),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(result.stderr or result.stdout)
    stdout = result.stdout.strip()
    json_start = stdout.find("{")
    if json_start < 0:
        raise SystemExit(result.stderr or result.stdout or "solc did not return JSON output")
    output = json.loads(stdout[json_start:])
    errors = [item for item in output.get("errors", []) if item.get("severity") == "error"]
    if errors:
        raise SystemExit(json.dumps(errors, indent=2))

    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    contracts = {}
    for source_name, source_contracts in output.get("contracts", {}).items():
        for contract_name, artifact in source_contracts.items():
            bytecode = artifact.get("evm", {}).get("bytecode", {}).get("object", "")
            payload = {
                "abi": artifact.get("abi", []),
                "bytecode": f"0x{bytecode}" if bytecode else "0x",
                "methodIdentifiers": artifact.get("evm", {}).get("methodIdentifiers", {}),
                "source": source_name,
            }
            contracts[contract_name] = payload
            (BUILD_DIR / f"{contract_name}.abi").write_text(json.dumps(payload["abi"], indent=2) + "\n", encoding="utf-8")
            (BUILD_DIR / f"{contract_name}.bin").write_text(payload["bytecode"] + "\n", encoding="utf-8")
            (BUILD_DIR / f"{contract_name}.methods.json").write_text(
                json.dumps(payload["methodIdentifiers"], indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

    bundle = {
        "schemaVersion": "mantlelens.p2_7_demo_contracts.v1",
        "chainId": 5003,
        "networkName": "Mantle Sepolia",
        "explorerBaseUrl": "https://sepolia.mantlescan.xyz",
        "contracts": {
            name: contracts[name]
            for name in ("MantleLensDemoToken", "MantleLensDemoSpender", "AssessmentLogger")
            if name in contracts
        },
    }
    PUBLIC_ARTIFACT.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {PUBLIC_ARTIFACT}")
    print(f"Wrote build artifacts under {BUILD_DIR}")


if __name__ == "__main__":
    main()
