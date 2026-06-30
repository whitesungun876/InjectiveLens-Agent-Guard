from __future__ import annotations

import json
import os
import string
from dataclasses import dataclass
from typing import Any
from urllib import request

from .hashutil import stable_hash


ASSESSMENT_LOGGER_SIGNATURE = (
    "recordAssessment(bytes32,bytes32,bytes32,bytes32,uint256,string,string,string,string)"
)
ASSESSMENT_LOGGER_EVENT_SIGNATURE = (
    "AssessmentRecorded(bytes32,bytes32,address,bytes32,bytes32,uint256,string,string,string,string)"
)
ASSESSMENT_ARGUMENT_TYPES = [
    "bytes32",
    "bytes32",
    "bytes32",
    "bytes32",
    "uint256",
    "string",
    "string",
    "string",
    "string",
]
ASSESSMENT_EVENT_DATA_TYPES = [
    "bytes32",
    "bytes32",
    "uint256",
    "string",
    "string",
    "string",
    "string",
]


class OnchainUnavailable(RuntimeError):
    """Raised when required configuration or signing support is missing."""


class OnchainSubmissionError(RuntimeError):
    """Raised when an RPC call rejects the signed assessment record transaction."""


class OnchainReadbackError(RuntimeError):
    """Raised when read-only assessment verification cannot complete safely."""


@dataclass(frozen=True)
class AssessmentRecorderConfig:
    rpc_url: str | None = "https://rpc.mantle.xyz"
    chain_id: int = 5000
    contract_address: str | None = None
    private_key: str | None = None
    explorer_base_url: str = "https://mantlescan.xyz"

    @classmethod
    def from_env(cls) -> "AssessmentRecorderConfig":
        return cls(
            rpc_url=_optional_env("MANTLE_RPC_URL", "https://rpc.mantle.xyz"),
            chain_id=int(os.getenv("MANTLE_CHAIN_ID") or os.getenv("CHAIN_ID") or "5000"),
            contract_address=_optional_env("ASSESSMENT_CONTRACT_ADDRESS")
            or _optional_env("ASSESSMENT_LOGGER_ADDRESS"),
            private_key=_optional_env("PRIVATE_KEY") or _optional_env("WALLET_PRIVATE_KEY"),
            explorer_base_url=os.getenv("MANTLE_EXPLORER_BASE_URL", "https://mantlescan.xyz").rstrip("/"),
        )

    @property
    def network_name(self) -> str:
        if self.chain_id == 5003:
            return "Mantle Sepolia"
        if self.chain_id == 5000:
            return "Mantle Mainnet"
        return f"Mantle Chain {self.chain_id}"


class AssessmentRecorder:
    def __init__(self, config: AssessmentRecorderConfig | None = None) -> None:
        self.config = config or AssessmentRecorderConfig.from_env()

    @classmethod
    def from_env(cls) -> "AssessmentRecorder":
        return cls(AssessmentRecorderConfig.from_env())

    def record_assessment(
        self,
        assessment: dict[str, Any],
        *,
        assessment_uri: str,
        trace_id: str,
    ) -> dict[str, Any]:
        unavailable = self._missing_configuration()
        if unavailable:
            return self._unavailable(unavailable)
        try:
            tx_hash = SignedAssessmentTransactionSender(self.config).send(
                assessment,
                assessment_uri=assessment_uri,
                trace_id=trace_id,
            )
        except OnchainUnavailable as exc:
            return self._unavailable(str(exc))
        except Exception as exc:
            return {
                "status": "pending_retry",
                "commitMode": "onchain_pending_retry",
                "assessmentTx": None,
                "explorerUrl": None,
                "onchainRecordAvailable": False,
                "onchainWriteAttempted": True,
                "unavailableReason": None,
                "retryReason": str(exc),
                "contractAddress": self.config.contract_address,
                "chainId": self.config.chain_id,
                "networkName": self.config.network_name,
                "signerAddress": None,
            }
        return {
            "status": "recorded",
            "commitMode": "onchain",
            "assessmentTx": tx_hash,
            "explorerUrl": self._explorer_url(tx_hash),
            "onchainRecordAvailable": True,
            "onchainWriteAttempted": True,
            "unavailableReason": None,
            "retryReason": None,
            "contractAddress": self.config.contract_address,
            "chainId": self.config.chain_id,
            "networkName": self.config.network_name,
            "signerAddress": None,
        }

    def _missing_configuration(self) -> str | None:
        if not self.config.contract_address:
            return "ASSESSMENT_CONTRACT_ADDRESS/ASSESSMENT_LOGGER_ADDRESS is not configured"
        if not self.config.private_key:
            return "PRIVATE_KEY/WALLET_PRIVATE_KEY is not configured"
        if not self.config.rpc_url:
            return "MANTLE_RPC_URL is not configured"
        return None

    def _unavailable(self, reason: str) -> dict[str, Any]:
        return {
            "status": "pending_unavailable",
            "commitMode": "onchain_unavailable",
            "assessmentTx": None,
            "explorerUrl": None,
            "onchainRecordAvailable": False,
            "onchainWriteAttempted": False,
            "unavailableReason": reason,
            "retryReason": None,
            "contractAddress": self.config.contract_address,
            "chainId": self.config.chain_id,
            "networkName": self.config.network_name,
            "signerAddress": None,
        }

    def _explorer_url(self, tx_hash: str) -> str:
        return f"{self.config.explorer_base_url}/tx/{tx_hash}"


def build_assessment_commit_calldata(
    assessment: dict[str, Any],
    *,
    assessment_uri: str | None = None,
    config: "AssessmentVerifierConfig | None" = None,
) -> dict[str, Any]:
    """Prepare AssessmentLogger calldata for a browser wallet to submit.

    This helper is intentionally signing-free. It does not read a private key,
    never calls eth_sendRawTransaction, and returns only calldata that a user
    can explicitly confirm in a wallet extension.
    """

    calldata_config = config or AssessmentVerifierConfig.from_env()
    if not _is_address(calldata_config.contract_address or ""):
        raise OnchainReadbackError("ASSESSMENT_CONTRACT_ADDRESS/ASSESSMENT_LOGGER_ADDRESS is not configured")
    if int(assessment.get("chainId") or calldata_config.chain_id) != int(calldata_config.chain_id):
        raise OnchainReadbackError("assessment chainId does not match configured AssessmentLogger chain")
    _, encode, keccak = _abi_helpers()
    selector = keccak(text=ASSESSMENT_LOGGER_SIGNATURE)[:4]
    args = _assessment_record_args(
        assessment,
        assessment_uri=assessment_uri or f"mantlelens://assessment/{assessment.get('assessmentId') or assessment.get('assessmentHash')}",
    )
    data = "0x" + (selector + encode(ASSESSMENT_ARGUMENT_TYPES, args)).hex()
    return {
        "status": "ready",
        "method": "recordAssessment",
        "to": calldata_config.contract_address,
        "contractAddress": calldata_config.contract_address,
        "chainId": calldata_config.chain_id,
        "networkName": calldata_config.network_name,
        "explorerBaseUrl": calldata_config.explorer_base_url,
        "value": "0x0",
        "data": data,
        "assessmentHash": _bytes_to_hex(args[0]),
        "walletHash": _bytes_to_hex(args[1]),
        "evidenceBundleHash": _bytes_to_hex(args[2]),
        "recommendationHash": _bytes_to_hex(args[3]),
        "walletRiskScoreBps": args[4],
        "privateKeyRequired": False,
        "walletConfirmationRequired": True,
        "onchainWriteAttempted": False,
        "safety": {
            "serverSigned": False,
            "serverBroadcast": False,
            "userWalletMustConfirm": True,
        },
    }


@dataclass(frozen=True)
class AssessmentVerifierConfig:
    rpc_url: str | None = "https://rpc.mantle.xyz"
    chain_id: int = 5003
    contract_address: str | None = None
    explorer_base_url: str = "https://sepolia.mantlescan.xyz"

    @classmethod
    def from_env(cls) -> "AssessmentVerifierConfig":
        return cls(
            rpc_url=_optional_env("MANTLE_RPC_URL", "https://rpc.mantle.xyz"),
            chain_id=int(os.getenv("MANTLE_CHAIN_ID") or os.getenv("CHAIN_ID") or "5003"),
            contract_address=_optional_env("ASSESSMENT_CONTRACT_ADDRESS")
            or _optional_env("ASSESSMENT_LOGGER_ADDRESS"),
            explorer_base_url=os.getenv("MANTLE_EXPLORER_BASE_URL", "https://sepolia.mantlescan.xyz").rstrip("/"),
        )

    @property
    def network_name(self) -> str:
        return _network_name(self.chain_id)


class AssessmentReadbackVerifier:
    """Read-only verifier for AssessmentLogger commits.

    This class intentionally uses JSON-RPC read methods only. It never imports
    a signer, never reads a private key, and never calls eth_sendRawTransaction.
    """

    def __init__(
        self,
        config: AssessmentVerifierConfig | None = None,
        rpc: "JsonRpcClient | None" = None,
    ) -> None:
        self.config = config or AssessmentVerifierConfig.from_env()
        self.rpc = rpc or JsonRpcClient(self.config.rpc_url or "")

    @classmethod
    def from_env(cls) -> "AssessmentReadbackVerifier":
        return cls(AssessmentVerifierConfig.from_env())

    def verify_tx(
        self,
        tx_hash: str,
        *,
        expected_assessment_hash: str | None = None,
    ) -> dict[str, Any]:
        normalized_tx_hash = _normalize_tx_hash(tx_hash)
        if normalized_tx_hash is None:
            return self._result(
                "unknown",
                tx_hash=tx_hash,
                safe_error="tx_hash must be a 32-byte hex string",
            )
        if not self.config.rpc_url:
            return self._result(
                "unknown",
                tx_hash=normalized_tx_hash,
                safe_error="Mantle Sepolia RPC provider is not configured",
            )
        if not _is_address(self.config.contract_address or ""):
            return self._result(
                "unknown",
                tx_hash=normalized_tx_hash,
                safe_error="ASSESSMENT_CONTRACT_ADDRESS/ASSESSMENT_LOGGER_ADDRESS is not configured",
            )

        try:
            provider_chain_id = _hex_to_int(self.rpc.call("eth_chainId", []))
            if provider_chain_id != 5003:
                return self._result(
                    "mismatch",
                    tx_hash=normalized_tx_hash,
                    chain_id=provider_chain_id,
                    network_name=_network_name(provider_chain_id),
                    mismatch_reason="RPC provider is not Mantle Sepolia chain id 5003",
                )
            if self.config.chain_id != 5003:
                return self._result(
                    "mismatch",
                    tx_hash=normalized_tx_hash,
                    chain_id=self.config.chain_id,
                    network_name=self.config.network_name,
                    mismatch_reason="Configured chain id is not Mantle Sepolia 5003",
                )

            tx = self.rpc.call("eth_getTransactionByHash", [normalized_tx_hash])
            if not tx:
                return self._result(
                    "unknown",
                    tx_hash=normalized_tx_hash,
                    chain_id=provider_chain_id,
                    network_name="Mantle Sepolia",
                    safe_error="Transaction was not found by the configured RPC provider",
                )

            tx_chain_id = tx.get("chainId")
            if tx_chain_id is not None and _hex_to_int(tx_chain_id) != 5003:
                return self._result(
                    "mismatch",
                    tx_hash=normalized_tx_hash,
                    chain_id=_hex_to_int(tx_chain_id),
                    network_name=_network_name(_hex_to_int(tx_chain_id)),
                    mismatch_reason="Transaction chain id is not Mantle Sepolia 5003",
                )

            configured_contract = (self.config.contract_address or "").lower()
            tx_target = str(tx.get("to") or "").lower()
            if tx_target != configured_contract:
                return self._result(
                    "mismatch",
                    tx_hash=normalized_tx_hash,
                    chain_id=provider_chain_id,
                    network_name="Mantle Sepolia",
                    mismatch_reason="Transaction target does not match configured AssessmentLogger contract",
                )

            receipt = self.rpc.call("eth_getTransactionReceipt", [normalized_tx_hash])
            if not receipt:
                return self._result(
                    "pending",
                    tx_hash=normalized_tx_hash,
                    chain_id=provider_chain_id,
                    network_name="Mantle Sepolia",
                )

            block_number = _hex_to_int(receipt.get("blockNumber")) if receipt.get("blockNumber") else None
            if _hex_to_int(receipt.get("status")) == 0:
                return self._result(
                    "failed",
                    tx_hash=normalized_tx_hash,
                    chain_id=provider_chain_id,
                    network_name="Mantle Sepolia",
                    block_number=block_number,
                )

            call_record = self._decode_call_data(tx.get("input") or tx.get("data"))
            event_record = self._decode_receipt_event(receipt)
            if call_record is None and event_record is None:
                return self._result(
                    "mismatch",
                    tx_hash=normalized_tx_hash,
                    chain_id=provider_chain_id,
                    network_name="Mantle Sepolia",
                    block_number=block_number,
                    mismatch_reason="Transaction does not match AssessmentLogger recordAssessment calldata or AssessmentRecorded event",
                )

            record = event_record or call_record or {}
            assessment_hash = record.get("assessmentHash")
            record_id = record.get("recordId")
            if expected_assessment_hash and assessment_hash and _normalize_hash32(expected_assessment_hash) != assessment_hash:
                return self._result(
                    "mismatch",
                    tx_hash=normalized_tx_hash,
                    chain_id=provider_chain_id,
                    network_name="Mantle Sepolia",
                    block_number=block_number,
                    event_name=event_record.get("eventName") if event_record else None,
                    assessment_hash=assessment_hash,
                    record_id=record_id,
                    mismatch_reason="Assessment hash does not match local assessment record",
                )

            return self._result(
                "verified",
                tx_hash=normalized_tx_hash,
                chain_id=provider_chain_id,
                network_name="Mantle Sepolia",
                block_number=block_number,
                event_name=event_record.get("eventName") if event_record else None,
                assessment_hash=assessment_hash,
                record_id=record_id,
            )
        except OnchainReadbackError as exc:
            return self._result("unknown", tx_hash=normalized_tx_hash, safe_error=str(exc))
        except Exception:
            return self._result(
                "unknown",
                tx_hash=normalized_tx_hash,
                safe_error="Read-only AssessmentLogger verification failed",
            )

    def _decode_call_data(self, input_data: Any) -> dict[str, Any] | None:
        if not isinstance(input_data, str):
            return None
        selector = _function_selector()
        if not input_data.startswith("0x") or input_data[:10].lower() != selector:
            return None
        decode, _, _ = _abi_helpers()
        try:
            decoded = decode(ASSESSMENT_ARGUMENT_TYPES, bytes.fromhex(input_data[10:]))
        except Exception as exc:
            raise OnchainReadbackError("AssessmentLogger calldata could not be decoded") from exc
        return {
            "functionName": "recordAssessment",
            "assessmentHash": _bytes_to_hex(decoded[0]),
            "walletHash": _bytes_to_hex(decoded[1]),
            "evidenceBundleHash": _bytes_to_hex(decoded[2]),
            "recommendationHash": _bytes_to_hex(decoded[3]),
            "walletRiskScoreBps": int(decoded[4]),
            "riskLevel": str(decoded[5]),
            "decisionType": str(decoded[6]),
            "actionType": str(decoded[7]),
            "assessmentURI": str(decoded[8]),
        }

    def _decode_receipt_event(self, receipt: dict[str, Any]) -> dict[str, Any] | None:
        _, _, keccak = _abi_helpers()
        event_topic = "0x" + keccak(text=ASSESSMENT_LOGGER_EVENT_SIGNATURE).hex()
        contract_address = (self.config.contract_address or "").lower()
        for log in receipt.get("logs") or []:
            topics = log.get("topics") or []
            if not topics or str(topics[0]).lower() != event_topic.lower():
                continue
            if str(log.get("address") or "").lower() != contract_address:
                continue
            if len(topics) < 4:
                raise OnchainReadbackError("AssessmentRecorded event is missing indexed topics")
            decode, _, _ = _abi_helpers()
            try:
                decoded = decode(ASSESSMENT_EVENT_DATA_TYPES, bytes.fromhex(str(log.get("data") or "0x")[2:]))
            except Exception as exc:
                raise OnchainReadbackError("AssessmentRecorded event data could not be decoded") from exc
            assessment_hash = _normalize_hash32(str(topics[1])) or str(topics[1]).lower()
            signer = _topic_to_address(str(topics[3]))
            return {
                "eventName": "AssessmentRecorded",
                "assessmentHash": assessment_hash,
                "walletHash": _normalize_hash32(str(topics[2])) or str(topics[2]).lower(),
                "signerAddress": signer,
                "evidenceBundleHash": _bytes_to_hex(decoded[0]),
                "recommendationHash": _bytes_to_hex(decoded[1]),
                "walletRiskScoreBps": int(decoded[2]),
                "riskLevel": str(decoded[3]),
                "decisionType": str(decoded[4]),
                "actionType": str(decoded[5]),
                "assessmentURI": str(decoded[6]),
                "recordId": _record_id(assessment_hash, signer),
            }
        return None

    def _result(
        self,
        verification_status: str,
        *,
        tx_hash: str,
        chain_id: int | None = None,
        network_name: str | None = None,
        block_number: int | None = None,
        event_name: str | None = None,
        assessment_hash: str | None = None,
        record_id: str | None = None,
        mismatch_reason: str | None = None,
        safe_error: str | None = None,
    ) -> dict[str, Any]:
        return {
            "status": verification_status,
            "verificationStatus": verification_status,
            "chainId": chain_id if chain_id is not None else self.config.chain_id,
            "networkName": network_name or self.config.network_name,
            "contractAddress": self.config.contract_address,
            "txHash": tx_hash,
            "explorerUrl": f"{self.config.explorer_base_url}/tx/{tx_hash}" if _normalize_tx_hash(tx_hash) else None,
            "blockNumber": block_number,
            "eventName": event_name,
            "assessmentHash": assessment_hash,
            "recordId": record_id,
            "mismatchReason": mismatch_reason,
            "safeError": safe_error,
        }


class LocalOnlyAssessmentRecorder:
    def record_assessment(
        self,
        assessment: dict[str, Any],
        *,
        assessment_uri: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return {
            "status": "recorded_local",
            "commitMode": "local_only",
            "assessmentTx": None,
            "explorerUrl": None,
            "onchainRecordAvailable": False,
            "onchainWriteAttempted": False,
            "unavailableReason": None,
            "retryReason": None,
            "contractAddress": None,
            "chainId": int(assessment.get("chainId") or 5000),
            "networkName": _network_name(int(assessment.get("chainId") or 5000)),
            "signerAddress": None,
        }


class UnavailableAssessmentRecorder:
    def __init__(self, reason: str = "on-chain assessment recorder disabled for this run") -> None:
        self.reason = reason

    def record_assessment(
        self,
        assessment: dict[str, Any],
        *,
        assessment_uri: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return {
            "status": "pending_unavailable",
            "commitMode": "onchain_unavailable",
            "assessmentTx": None,
            "explorerUrl": None,
            "onchainRecordAvailable": False,
            "onchainWriteAttempted": False,
            "unavailableReason": self.reason,
            "retryReason": None,
            "contractAddress": None,
            "chainId": int(assessment.get("chainId") or 5000),
            "networkName": _network_name(int(assessment.get("chainId") or 5000)),
            "signerAddress": None,
        }


class SignedAssessmentTransactionSender:
    def __init__(self, config: AssessmentRecorderConfig) -> None:
        self.config = config

    def send(self, assessment: dict[str, Any], *, assessment_uri: str, trace_id: str) -> str:
        try:
            from eth_abi import encode
            from eth_account import Account
            from eth_utils import keccak, to_checksum_address
        except ModuleNotFoundError as exc:
            raise OnchainUnavailable(
                "Optional Python packages eth-account and eth-abi are required for signed on-chain assessment commits."
            ) from exc

        if not _is_address(self.config.contract_address or ""):
            raise OnchainUnavailable("ASSESSMENT_CONTRACT_ADDRESS must be a 20-byte hex address")
        if not self.config.private_key:
            raise OnchainUnavailable("PRIVATE_KEY/WALLET_PRIVATE_KEY is not configured")

        account = Account.from_key(_normalize_private_key(self.config.private_key))
        contract_address = to_checksum_address(self.config.contract_address or "")
        selector = keccak(text=ASSESSMENT_LOGGER_SIGNATURE)[:4]
        args = _assessment_record_args(assessment, assessment_uri=assessment_uri)
        data = "0x" + (selector + encode(
            ["bytes32", "bytes32", "bytes32", "bytes32", "uint256", "string", "string", "string", "string"],
            args,
        )).hex()

        rpc = JsonRpcClient(self.config.rpc_url or "")
        nonce = _hex_to_int(rpc.call("eth_getTransactionCount", [account.address, "latest"]))
        gas_price = _hex_to_int(rpc.call("eth_gasPrice", []))
        gas = self._estimate_gas(rpc, account.address, contract_address, data)
        signed = Account.sign_transaction(
            {
                "chainId": self.config.chain_id,
                "to": contract_address,
                "value": 0,
                "nonce": nonce,
                "gas": gas,
                "gasPrice": gas_price,
                "data": data,
            },
            _normalize_private_key(self.config.private_key),
        )
        raw_tx = getattr(signed, "rawTransaction", None) or getattr(signed, "raw_transaction", None)
        if raw_tx is None:
            raise OnchainSubmissionError("Signed transaction did not expose raw bytes")
        raw_hex = "0x" + bytes(raw_tx).hex()
        return rpc.call("eth_sendRawTransaction", [raw_hex])

    def _estimate_gas(self, rpc: "JsonRpcClient", signer_address: str, contract_address: str, data: str) -> int:
        tx_args = {
            "from": signer_address,
            "to": contract_address,
            "data": data,
        }
        try:
            estimated = _hex_to_int(rpc.call("eth_estimateGas", [tx_args]))
        except OnchainSubmissionError:
            estimated = 250000
        return max(180000, int(estimated * 1.2))


class JsonRpcClient:
    def __init__(self, rpc_url: str, timeout: int = 20) -> None:
        self.rpc_url = rpc_url
        self.timeout = timeout

    def call(self, method: str, params: list[Any]) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        }
        req = request.Request(
            self.rpc_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise OnchainSubmissionError(f"RPC request failed for {method}: {exc}") from exc
        if data.get("error"):
            raise OnchainSubmissionError(f"RPC {method} error: {data['error']}")
        return data.get("result")


def _optional_env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value or None


def _network_name(chain_id: int) -> str:
    if chain_id == 5003:
        return "Mantle Sepolia"
    if chain_id == 5000:
        return "Mantle Mainnet"
    return f"Mantle Chain {chain_id}"


def _normalize_private_key(private_key: str) -> str:
    return private_key if private_key.startswith("0x") else f"0x{private_key}"


def _is_address(value: str) -> bool:
    return value.startswith("0x") and len(value) == 42 and all(char in string.hexdigits for char in value[2:])


def _bytes32(value: Any) -> bytes:
    text = str(value)
    if text.startswith("0x") and len(text) == 66 and all(char in string.hexdigits for char in text[2:]):
        return bytes.fromhex(text[2:])
    return bytes.fromhex(stable_hash(value)[2:])


def _assessment_record_args(assessment: dict[str, Any], *, assessment_uri: str) -> list[Any]:
    return [
        _bytes32(assessment["assessmentHash"]),
        _bytes32(assessment["wallet"]["walletHash"]),
        _bytes32(assessment["evidenceBundleHash"]),
        _bytes32(assessment["recommendationHash"]),
        int(round(float(assessment["walletRiskScore"]) * 100)),
        str(assessment["riskLevel"]),
        str(assessment["decisionType"]),
        str(assessment["actionType"]),
        assessment_uri,
    ]


def _hex_to_int(value: str | int | None) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    return int(value, 16) if value.startswith("0x") else int(value)


def _normalize_tx_hash(value: Any) -> str | None:
    text = str(value or "").strip()
    if text.startswith("0x") and len(text) == 66 and all(char in string.hexdigits for char in text[2:]):
        return text.lower()
    return None


def _normalize_hash32(value: Any) -> str | None:
    return _normalize_tx_hash(value)


def _bytes_to_hex(value: Any) -> str:
    return "0x" + bytes(value).hex()


def _topic_to_address(topic: str) -> str:
    text = topic.lower()
    if text.startswith("0x") and len(text) == 66:
        return "0x" + text[-40:]
    return text


def _function_selector() -> str:
    _, _, keccak = _abi_helpers()
    return "0x" + keccak(text=ASSESSMENT_LOGGER_SIGNATURE)[:4].hex()


def _record_id(assessment_hash: str | None, signer_address: str | None) -> str | None:
    if not assessment_hash or not signer_address:
        return None
    normalized_assessment_hash = _normalize_hash32(assessment_hash)
    if normalized_assessment_hash is None or not _is_address(signer_address):
        return None
    _, _, keccak = _abi_helpers()
    payload = bytes.fromhex(normalized_assessment_hash[2:]) + bytes.fromhex(signer_address[2:])
    return "0x" + keccak(payload).hex()


def _abi_helpers() -> tuple[Any, Any, Any]:
    try:
        from eth_abi import decode, encode
        from eth_utils import keccak
    except ModuleNotFoundError as exc:
        raise OnchainReadbackError(
            "Optional Python packages eth-abi and eth-utils are required for AssessmentLogger readback verification"
        ) from exc
    return decode, encode, keccak
