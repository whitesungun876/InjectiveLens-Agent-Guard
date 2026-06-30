#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "contracts" / "AssessmentLogger.sol"
BUILD_DIR = ROOT / "build" / "assessment-logger"

sys.path.insert(0, str(ROOT))

from backend.mantlelens.onchain import JsonRpcClient, OnchainSubmissionError  # noqa: E402


def main() -> int:
    load_dotenv(ROOT / ".env")
    rpc_url = optional_env("DEPLOY_RPC_URL") or optional_env("MANTLE_RPC_URL") or optional_env("TENDERLY_NODE_RPC_URL")
    private_key = (
        optional_env("PRIVATE_KEY") or optional_env("WALLET_PRIVATE_KEY") or optional_env("SIGNER_PRIVATE_KEY")
    )
    chain_id = int(optional_env("MANTLE_CHAIN_ID") or optional_env("CHAIN_ID") or "5000")

    if not rpc_url:
        print("Missing RPC URL. Set DEPLOY_RPC_URL, MANTLE_RPC_URL, or TENDERLY_NODE_RPC_URL.", file=sys.stderr)
        return 2
    if not private_key:
        print("Missing deployer key. Set PRIVATE_KEY, WALLET_PRIVATE_KEY, or SIGNER_PRIVATE_KEY.", file=sys.stderr)
        return 2

    try:
        from eth_account import Account
    except ModuleNotFoundError:
        print("Missing eth-account. Run: python3 -m pip install -r requirements.onchain.txt", file=sys.stderr)
        return 2

    bytecode = compile_contract()
    account = Account.from_key(normalize_private_key(private_key))
    rpc = JsonRpcClient(rpc_url, timeout=30)
    nonce = hex_to_int(rpc.call("eth_getTransactionCount", [account.address, "latest"]))
    gas_price = hex_to_int(rpc.call("eth_gasPrice", []))
    gas = estimate_deploy_gas(rpc, account.address, bytecode)

    signed = Account.sign_transaction(
        {
            "chainId": chain_id,
            "value": 0,
            "nonce": nonce,
            "gas": gas,
            "gasPrice": gas_price,
            "data": "0x" + bytecode,
        },
        normalize_private_key(private_key),
    )
    raw_tx = getattr(signed, "rawTransaction", None) or getattr(signed, "raw_transaction", None)
    if raw_tx is None:
        print("Signed transaction did not expose raw bytes.", file=sys.stderr)
        return 1

    tx_hash = rpc.call("eth_sendRawTransaction", ["0x" + bytes(raw_tx).hex()])
    receipt = wait_for_receipt(rpc, tx_hash)
    contract_address = receipt.get("contractAddress") if isinstance(receipt, dict) else None

    print(f"AssessmentLogger deployment tx: {tx_hash}")
    if contract_address:
        print(f"AssessmentLogger deployed to: {contract_address}")
        print(f"ASSESSMENT_CONTRACT_ADDRESS={contract_address}")
        print(f"ASSESSMENT_LOGGER_ADDRESS={contract_address}")
    else:
        print("Deployment submitted but contract address is not in the receipt yet.")
    return 0


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def compile_contract() -> str:
    if not CONTRACT_PATH.exists():
        raise SystemExit(f"Missing contract: {CONTRACT_PATH}")
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    for artifact in BUILD_DIR.glob("*AssessmentLogger*"):
        artifact.unlink()
    source_key = str(CONTRACT_PATH.relative_to(ROOT))
    compiler_input = {
        "language": "Solidity",
        "sources": {source_key: {"content": CONTRACT_PATH.read_text(encoding="utf-8")}},
        "settings": {
            "optimizer": {"enabled": True, "runs": 200},
            "viaIR": True,
            "outputSelection": {"*": {"*": ["abi", "evm.bytecode.object"]}},
        },
    }
    command = [
        "npx",
        "--yes",
        "solc@0.8.20",
        "--standard-json",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            input=json.dumps(compiler_input),
            text=True,
            capture_output=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise SystemExit("Missing npx/node. Install Node.js or compile the contract with Foundry/Hardhat.") from exc
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"solc compile failed with exit code {exc.returncode}: {exc.stderr}") from exc

    output = parse_solc_output(completed.stdout)
    errors = [item for item in output.get("errors", []) if item.get("severity") == "error"]
    if errors:
        messages = "\n".join(str(item.get("formattedMessage") or item.get("message")) for item in errors)
        raise SystemExit(messages)
    contract = output.get("contracts", {}).get(source_key, {}).get("AssessmentLogger")
    if not contract:
        raise SystemExit("solc output did not include AssessmentLogger.")
    bytecode = contract.get("evm", {}).get("bytecode", {}).get("object", "")
    abi = contract.get("abi", [])
    if not re.fullmatch(r"[0-9a-fA-F]+", bytecode):
        raise SystemExit("Compiled bytecode is invalid.")
    (BUILD_DIR / "AssessmentLogger.bin").write_text(bytecode + "\n", encoding="utf-8")
    (BUILD_DIR / "AssessmentLogger.abi").write_text(json.dumps(abi, indent=2) + "\n", encoding="utf-8")
    return bytecode


def parse_solc_output(raw: str) -> dict[str, Any]:
    start = raw.find("{")
    if start < 0:
        raise SystemExit("solc did not return JSON output.")
    return json.loads(raw[start:])


def estimate_deploy_gas(rpc: JsonRpcClient, from_address: str, bytecode: str) -> int:
    try:
        estimated = hex_to_int(rpc.call("eth_estimateGas", [{"from": from_address, "data": "0x" + bytecode}]))
    except OnchainSubmissionError:
        estimated = 700000
    return max(500000, int(estimated * 1.2))


def wait_for_receipt(rpc: JsonRpcClient, tx_hash: str) -> dict[str, Any] | None:
    for _ in range(45):
        receipt = rpc.call("eth_getTransactionReceipt", [tx_hash])
        if receipt:
            return receipt
        time.sleep(2)
    return None


def optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def normalize_private_key(private_key: str) -> str:
    return private_key if private_key.startswith("0x") else f"0x{private_key}"


def hex_to_int(value: str | int | None) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    return int(value, 16) if value.startswith("0x") else int(value)


if __name__ == "__main__":
    raise SystemExit(main())
