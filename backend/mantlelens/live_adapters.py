from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib import parse, request

from .adapters import ToolResult
from .chain_targets import ChainTarget
from .config import KnownToken, MantleLensConfig
from .hashutil import stable_hash
from .inventory import HistoryPageOptions, PaginatedHistoryResult, TokenInventoryNormalizer, dedupe_rows


APPROVAL_TOPIC0 = "0x8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925"
NFT_APPROVAL_FOR_ALL_TOPIC0 = "0x17307eab39ab6107e889984fe8b4e9f3f3f0f3b45a1de1f8205894b0b11b2d3d"
TRANSFER_TOPIC0 = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
UINT256_MAX = 2**256 - 1
ADDRESS_PATTERN = re.compile(r"^0x[a-fA-F0-9]{40}$")


class SourceUnavailable(RuntimeError):
    pass


class JsonHttpClient:
    def __init__(self, *, timeout: float = 3.0, retries: int = 1, retry_backoff: float = 0.15) -> None:
        self.timeout = timeout
        self.retries = retries
        self.retry_backoff = retry_backoff

    def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        query = parse.urlencode({key: value for key, value in (params or {}).items() if value is not None})
        target = f"{url}?{query}" if query else url
        req = request.Request(target, headers=headers or {}, method="GET")
        return self._urlopen_json(req, timeout=timeout)

    def post_json(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        req_headers = {"Content-Type": "application/json"}
        req_headers.update(headers or {})
        req = request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=req_headers,
            method="POST",
        )
        return self._urlopen_json(req, timeout=timeout)

    def _urlopen_json(self, req: request.Request, *, timeout: float | None) -> dict[str, Any]:
        attempts = self.retries + 1
        last_error: Exception | None = None
        request_timeout = self.timeout if timeout is None else timeout
        for attempt in range(attempts):
            try:
                with request.urlopen(req, timeout=request_timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except Exception as exc:
                last_error = exc
                if attempt >= attempts - 1:
                    break
                time.sleep(self.retry_backoff * (attempt + 1))
        raise SourceUnavailable(f"HTTP request failed after {attempts} attempt(s): {last_error}") from last_error


@dataclass
class MantleRpcClient:
    rpc_url: str
    http: JsonHttpClient

    def call(self, method: str, params: list[Any]) -> Any:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        data = self.http.post_json(self.rpc_url, payload)
        if data.get("error"):
            raise SourceUnavailable(str(data["error"]))
        return data.get("result")

    def native_balance(self, wallet_address: str) -> int:
        result = self.call("eth_getBalance", [wallet_address, "latest"])
        return _hex_to_int(result)

    def erc20_balance_of(self, token_address: str, wallet_address: str) -> int:
        result = self.call(
            "eth_call",
            [
                {
                    "to": token_address,
                    "data": "0x70a08231" + _abi_address(wallet_address),
                },
                "latest",
            ],
        )
        return _hex_to_int(result)

    def erc20_allowance(self, token_address: str, owner: str, spender: str) -> int:
        result = self.call(
            "eth_call",
            [
                {
                    "to": token_address,
                    "data": "0xdd62ed3e" + _abi_address(owner) + _abi_address(spender),
                },
                "latest",
            ],
        )
        return _hex_to_int(result)

    def nft_is_approved_for_all(self, token_address: str, owner: str, operator: str) -> bool:
        result = self.call(
            "eth_call",
            [
                {
                    "to": token_address,
                    "data": "0xe985e9c5" + _abi_address(owner) + _abi_address(operator),
                },
                "latest",
            ],
        )
        return _hex_to_int(result) > 0


@dataclass
class GoPlusClient:
    config: MantleLensConfig
    http: JsonHttpClient

    def _headers(self) -> dict[str, str]:
        if self.config.goplus_api_key:
            return {"Authorization": f"Bearer {self.config.goplus_api_key}"}
        return {}

    def token_security(self, token_addresses: list[str]) -> dict[str, Any]:
        if not token_addresses:
            return {}
        data = self.http.get_json(
            f"{self.config.goplus_base_url}/api/v1/token_security/{self.config.chain_id}",
            params={"contract_addresses": ",".join(token_addresses)},
            headers=self._headers(),
        )
        result = data.get("result") or {}
        if not isinstance(result, dict):
            raise SourceUnavailable("GoPlus token security returned an unexpected shape")
        return result

    def address_security(self, address: str) -> dict[str, Any]:
        data = self.http.get_json(
            f"{self.config.goplus_base_url}/api/v1/address_security/{address}",
            params={"chain_id": self.config.chain_id},
            headers=self._headers(),
        )
        result = data.get("result") or data
        if not isinstance(result, dict):
            raise SourceUnavailable("GoPlus address security returned an unexpected shape")
        return result

    def approval_security(self, owner_address: str) -> dict[str, Any]:
        data = self.http.get_json(
            f"{self.config.goplus_base_url}/api/v2/token_approval_security/{self.config.chain_id}",
            params={"addresses": owner_address},
            headers=self._headers(),
        )
        result = data.get("result") or data
        if not isinstance(result, dict):
            raise SourceUnavailable("GoPlus approval security returned an unexpected shape")
        return result


@dataclass
class MoralisClient:
    config: MantleLensConfig
    http: JsonHttpClient

    def wallet_tokens(self, wallet_address: str) -> list[dict[str, Any]]:
        if not self.config.moralis_api_key:
            raise SourceUnavailable("MORALIS_API_KEY is not configured")
        data = self.http.get_json(
            f"{self.config.moralis_base_url}/wallets/{wallet_address}/tokens",
            params={"chain": self.config.moralis_chain, "limit": 100},
            headers={"X-API-Key": self.config.moralis_api_key},
        )
        result = data.get("result", data if isinstance(data, list) else [])
        if not isinstance(result, list):
            raise SourceUnavailable("Moralis token balances returned an unexpected shape")
        return result

    def wallet_history(self, wallet_address: str, *, limit: int = 100) -> list[dict[str, Any]]:
        if not self.config.moralis_api_key:
            raise SourceUnavailable("MORALIS_API_KEY is not configured")
        data = self.http.get_json(
            f"{self.config.moralis_base_url}/wallets/{wallet_address}/history",
            params={"chain": self.config.moralis_chain, "limit": limit},
            headers={"X-API-Key": self.config.moralis_api_key},
        )
        result = data.get("result", data if isinstance(data, list) else [])
        if not isinstance(result, list):
            raise SourceUnavailable("Moralis wallet history returned an unexpected shape")
        return result


@dataclass
class EtherscanV2Client:
    config: MantleLensConfig
    http: JsonHttpClient

    def query(self, params: dict[str, Any]) -> Any:
        if not self.config.etherscan_v2_api_key:
            raise SourceUnavailable("ETHERSCAN_V2_API_KEY or MANTLESCAN_API_KEY is not configured")
        data = self.http.get_json(
            self.config.etherscan_v2_base_url,
            params={
                "chainid": self.config.chain_id,
                "apikey": self.config.etherscan_v2_api_key,
                **params,
            },
        )
        status = str(data.get("status", "1"))
        message = str(data.get("message", "OK"))
        result = data.get("result", [])
        if status == "0" and "No" in message:
            return []
        if status == "0" and isinstance(result, str):
            raise SourceUnavailable(result)
        return result

    def token_transfers(
        self,
        wallet_address: str,
        *,
        page: int = 1,
        offset: int = 100,
        sort: str = "desc",
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        if limit is not None:
            offset = limit
        result = self.query(
            {
                "module": "account",
                "action": "tokentx",
                "address": wallet_address,
                "page": page,
                "offset": offset,
                "sort": sort,
            }
        )
        return result if isinstance(result, list) else []

    def token_transfers_paginated(
        self,
        wallet_address: str,
        options: HistoryPageOptions | None = None,
    ) -> PaginatedHistoryResult:
        page_options = options or HistoryPageOptions()
        rows: list[dict[str, Any]] = []
        fetched_pages = 0
        last_page_count = 0
        for page in page_options.pages():
            page_rows = self.token_transfers(
                wallet_address,
                page=page,
                offset=page_options.page_size,
                sort=page_options.sort,
            )
            fetched_pages += 1
            last_page_count = len(page_rows)
            rows.extend(page_rows)
            if len(page_rows) < page_options.page_size:
                break
        deduped = dedupe_rows(rows, keys=("hash", "contractAddress", "logIndex"))
        return PaginatedHistoryResult(
            rows=deduped,
            page_info=page_options.page_info(
                fetched_pages=fetched_pages,
                last_page_count=last_page_count,
                row_count=len(deduped),
            ),
        )

    def normal_transactions(
        self,
        wallet_address: str,
        *,
        page: int = 1,
        offset: int = 100,
        sort: str = "desc",
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        if limit is not None:
            offset = limit
        result = self.query(
            {
                "module": "account",
                "action": "txlist",
                "address": wallet_address,
                "page": page,
                "offset": offset,
                "sort": sort,
            }
        )
        return result if isinstance(result, list) else []

    def approval_logs(
        self,
        owner_address: str,
        *,
        page: int = 1,
        offset: int = 100,
        from_block: int = 0,
        to_block: str | int = "latest",
    ) -> list[dict[str, Any]]:
        result = self.query(
            {
                "module": "logs",
                "action": "getLogs",
                "fromBlock": from_block,
                "toBlock": to_block,
                "topic0": APPROVAL_TOPIC0,
                "topic1": _topic_address(owner_address),
                "page": page,
                "offset": offset,
            }
        )
        return result if isinstance(result, list) else []

    def approval_logs_paginated(
        self,
        owner_address: str,
        options: HistoryPageOptions | None = None,
    ) -> PaginatedHistoryResult:
        page_options = options or HistoryPageOptions()
        rows: list[dict[str, Any]] = []
        fetched_pages = 0
        last_page_count = 0
        for page in page_options.pages():
            page_rows = self.approval_logs(
                owner_address,
                page=page,
                offset=page_options.page_size,
                from_block=page_options.from_block,
                to_block=page_options.to_block,
            )
            fetched_pages += 1
            last_page_count = len(page_rows)
            rows.extend(page_rows)
            if len(page_rows) < page_options.page_size:
                break
        deduped = dedupe_rows(rows, keys=("transactionHash", "address", "logIndex"))
        return PaginatedHistoryResult(
            rows=deduped,
            page_info=page_options.page_info(
                fetched_pages=fetched_pages,
                last_page_count=last_page_count,
                row_count=len(deduped),
            ),
        )

    def nft_approval_for_all_logs(
        self,
        owner_address: str,
        *,
        page: int = 1,
        offset: int = 100,
        from_block: int = 0,
        to_block: str | int = "latest",
    ) -> list[dict[str, Any]]:
        result = self.query(
            {
                "module": "logs",
                "action": "getLogs",
                "fromBlock": from_block,
                "toBlock": to_block,
                "topic0": NFT_APPROVAL_FOR_ALL_TOPIC0,
                "topic1": _topic_address(owner_address),
                "page": page,
                "offset": offset,
            }
        )
        return result if isinstance(result, list) else []

    def nft_approval_for_all_logs_paginated(
        self,
        owner_address: str,
        options: HistoryPageOptions | None = None,
    ) -> PaginatedHistoryResult:
        page_options = options or HistoryPageOptions()
        rows: list[dict[str, Any]] = []
        fetched_pages = 0
        last_page_count = 0
        for page in page_options.pages():
            page_rows = self.nft_approval_for_all_logs(
                owner_address,
                page=page,
                offset=page_options.page_size,
                from_block=page_options.from_block,
                to_block=page_options.to_block,
            )
            fetched_pages += 1
            last_page_count = len(page_rows)
            rows.extend(page_rows)
            if len(page_rows) < page_options.page_size:
                break
        deduped = dedupe_rows(rows, keys=("transactionHash", "address", "logIndex"))
        return PaginatedHistoryResult(
            rows=deduped,
            page_info=page_options.page_info(
                fetched_pages=fetched_pages,
                last_page_count=last_page_count,
                row_count=len(deduped),
            ),
        )


class LiveWalletAdapter:
    """Read-only live wallet tools for Mantle P1.

    The adapter intentionally exposes the same raw tool shape as the fixture
    adapter so P0 replay tests can stay as the golden harness.
    """

    def __init__(
        self,
        *,
        config: MantleLensConfig | None = None,
        rpc: MantleRpcClient | None = None,
        goplus: GoPlusClient | None = None,
        moralis: MoralisClient | None = None,
        etherscan: EtherscanV2Client | None = None,
        http: JsonHttpClient | None = None,
        chain_target: ChainTarget | None = None,
    ) -> None:
        self.config = config or MantleLensConfig.from_env()
        self.chain_target = chain_target
        self.http = http or JsonHttpClient(
            timeout=self.config.live_request_timeout_sec,
            retries=self.config.live_request_retries,
        )
        self.rpc = rpc or (
            MantleRpcClient(self.config.effective_rpc_url, self.http) if self.config.effective_rpc_url else None
        )
        self.goplus = goplus or GoPlusClient(self.config, self.http)
        self.moralis = moralis or MoralisClient(self.config, self.http)
        self.etherscan = etherscan or EtherscanV2Client(self.config, self.http)

    @classmethod
    def from_env(cls) -> "LiveWalletAdapter":
        return cls(config=MantleLensConfig.from_env())

    def load_scan_subject(
        self,
        *,
        fixture_id: str | None = None,
        wallet_address: str | None = None,
        history_options: HistoryPageOptions | None = None,
    ) -> dict[str, Any]:
        if not wallet_address or not ADDRESS_PATTERN.match(wallet_address):
            raise ValueError("A valid 0x walletAddress is required for live data mode")
        wallet = wallet_address.lower()
        wallet_hash = stable_hash({"chainId": self.config.chain_id, "walletAddress": wallet})
        subject = {
            "fixtureId": fixture_id or f"live_{wallet[2:10]}",
            "wallet": {"address": wallet, "walletHash": wallet_hash},
            "chainId": self.config.chain_id,
            "dataMode": "live",
            "chainTarget": self._chain_target_payload(),
            "dataCompleteness": {
                "nativeBalance": "unavailable",
                "knownTokenBalances": "unavailable",
                "fullTokenInventory": "unavailable",
                "approvalEvents": "unavailable",
                "activeAllowanceConfirmation": "unavailable",
                "transactionHistory": "unavailable",
                "transferLogs": "unavailable",
                "spenderLabels": "partial",
                "tokenSecurity": "partial",
                "defiPositions": "unavailable",
                "rwaYieldExposure": "partial",
            },
            "sourceAvailability": self.config.source_snapshot(),
            "evidence": [],
            "_balances": [],
            "_approvals": [],
            "_transfers": [],
            "_inventory": None,
            "_history": {
                "wallet": wallet,
                "chainId": self.config.chain_id,
                "approvalHistory": {
                    "status": "unavailable",
                    "items": [],
                    "pageInfo": None,
                },
                "transferHistory": {
                    "status": "unavailable",
                    "items": [],
                    "pageInfo": None,
                },
            },
            "_pageCoverage": {},
            "_historyOptions": history_options or HistoryPageOptions(),
            "_scanDeadlineAt": time.monotonic() + self.config.live_scan_deadline_sec,
        }
        self._add_evidence(
            subject,
            evidence_id=f"ev_live_source_{wallet[2:10]}",
            evidence_type="rule",
            claim_text="Live scan uses configured Mantle RPC, GoPlus, Moralis, and Etherscan V2 sources with explicit partial-data handling.",
            source="MantleLens Live Adapter",
            endpoint="config:live_sources",
            raw_data=self.config.source_snapshot(),
            data_quality="fresh",
            limitation="Missing source credentials are treated as unknown, not safe.",
        )
        return subject

    def _chain_target_payload(self) -> dict[str, Any]:
        if self.chain_target:
            return self.chain_target.public_dict()
        return {
            "id": "mantle-mainnet" if self.config.chain_id == 5000 else "mantle-sepolia",
            "name": self.config.network_name,
            "chainId": self.config.chain_id,
            "environment": "mainnet" if self.config.chain_id == 5000 else "testnet",
            "nativeSymbol": "MNT",
            "enabled": True,
            "supportsReadOnlyScan": bool(self.config.effective_rpc_url),
            "supportsAssessmentCommit": bool(self.config.assessment_contract_address and self.config.wallet_private_key),
            "comingSoon": False,
            "label": f"{self.config.network_name} · {self.config.chain_id}",
        }

    def get_native_balance(self, subject: dict[str, Any]) -> ToolResult:
        if not self.rpc:
            return self._unavailable(subject, "getNativeBalance", "Mantle RPC is not configured.")
        wallet = subject["wallet"]["address"]
        try:
            balance_raw = self.rpc.native_balance(wallet)
        except Exception as exc:
            self._set_source(subject, "mantleRpc", "partial", str(exc))
            return self._unavailable(subject, "getNativeBalance", f"Mantle RPC error: {exc}")

        normalizer = TokenInventoryNormalizer(wallet=wallet, chain_id=self.config.chain_id)
        balance = normalizer.native_balance_item(balance_raw) or {
            "symbol": "MNT",
            "tokenAddress": "native",
            "balanceRaw": str(balance_raw),
            "balance": 0,
            "priceUsd": None,
            "valueUsd": 0.0,
            "evidenceId": f"ev_live_native_{wallet[2:10]}",
            "evidenceIds": [f"ev_live_native_{wallet[2:10]}"],
        }
        subject["_balances"] = [balance] + [item for item in subject.get("_balances", []) if item["tokenAddress"] != "native"]
        self._set_completeness(subject, "nativeBalance", "available")
        self._set_source(subject, "mantleRpc", "available", "Native balance read from Mantle RPC.")
        self._add_evidence(
            subject,
            evidence_id=balance["evidenceId"],
            evidence_type="balance",
            claim_text="Native MNT balance was read from Mantle RPC.",
            source="Mantle RPC",
            endpoint="eth_getBalance",
            raw_data={"balanceRaw": str(balance_raw)},
            data_quality="fresh",
        )
        return ToolResult(
            tool_name="getNativeBalance",
            source_status="available",
            data_coverage="native-only",
            output={"wallet": wallet, "balance": balance},
            limitation="Native balance alone does not prove the wallet is safe.",
        )

    def get_known_token_balances(self, subject: dict[str, Any]) -> ToolResult:
        wallet = subject["wallet"]["address"]
        if self.config.moralis_balances_available:
            try:
                balances = self._moralis_balances(subject)
            except Exception as exc:
                self._set_source(subject, "moralis", "partial", str(exc))
            else:
                subject["_balances"] = _merge_balances(subject.get("_balances", []), balances)
                normalizer = TokenInventoryNormalizer(wallet=wallet, chain_id=self.config.chain_id)
                subject["_inventory"] = normalizer.build_inventory(
                    tokens=list(subject.get("_balances", [])),
                    inventory_status="available",
                    source="moralis_data_api_wallet_tokens",
                )
                self._set_completeness(subject, "knownTokenBalances", "available")
                self._set_completeness(subject, "fullTokenInventory", "available")
                self._set_source(subject, "moralis", "available", "Full token inventory read from Moralis.")
                return ToolResult(
                    tool_name="getKnownTokenBalances",
                    source_status="available",
                    data_coverage="indexed-wallet-inventory",
                    output={"wallet": wallet, "balances": balances, "inventory": subject["_inventory"]},
                    limitation="Moralis marks possible spam tokens, but security interpretation still requires evidence checks.",
                )

        if self.rpc and self.config.etherscan_v2_api_key:
            try:
                page_result = self.etherscan.token_transfers_paginated(wallet, _history_options(subject))
            except Exception as exc:
                self._set_source(subject, "etherscanV2", "partial", str(exc))
                page_result = None
            if page_result is not None:
                normalizer = TokenInventoryNormalizer(wallet=wallet, chain_id=self.config.chain_id)
                candidates = normalizer.token_candidates_from_transfer_rows(page_result.rows)
                balances = []
                for candidate in candidates:
                    if self.is_scan_deadline_expired(subject):
                        self._set_source(subject, "mantleRpc", "partial", "Live scan deadline expired during ERC20 balance confirmations.")
                        break
                    try:
                        balance_raw = self.rpc.erc20_balance_of(candidate["tokenAddress"], wallet)
                    except Exception as exc:
                        self._add_evidence(
                            subject,
                            evidence_id=f"ev_live_balance_error_{stable_hash(candidate)[2:14]}",
                            evidence_type="balance",
                            claim_text=f"{candidate['symbol']} current balance could not be confirmed by RPC.",
                            source="Mantle RPC",
                            endpoint="ERC20.balanceOf",
                            raw_data={"tokenAddress": candidate["tokenAddress"], "error": str(exc)},
                            data_quality="missing",
                            limitation="Transfer-derived token candidate was not scored as current balance.",
                        )
                        continue
                    item = normalizer.balance_item_from_candidate(candidate, balance_raw=balance_raw)
                    if item is None:
                        continue
                    balances.append(item)
                    self._add_evidence(
                        subject,
                        evidence_id=item["evidenceId"],
                        evidence_type="balance",
                        claim_text=f"{item['symbol']} current balance was confirmed from a transfer-derived token candidate.",
                        source="Mantle RPC + Etherscan V2",
                        endpoint="account:tokentx + ERC20.balanceOf",
                        raw_data={
                            "tokenAddress": item["tokenAddress"],
                            "balanceRaw": item["balanceRaw"],
                            "candidateSource": item["candidateSource"],
                            "firstSeenBlock": item["firstSeenBlock"],
                            "lastSeenBlock": item["lastSeenBlock"],
                        },
                        data_quality="fresh",
                        limitation="Inventory is derived from indexed transfer candidates, so unseen tokens remain unknown.",
                    )
                subject["_balances"] = _merge_balances(subject.get("_balances", []), balances)
                inventory_tokens = list(subject.get("_balances", []))
                subject["_inventory"] = normalizer.build_inventory(
                    tokens=inventory_tokens,
                    inventory_status="partial",
                    source="etherscan_v2_candidates_rpc_balanceOf",
                )
                subject["_pageCoverage"]["tokenInventoryCandidates"] = page_result.page_info
                self._set_completeness(subject, "knownTokenBalances", "partial")
                self._set_completeness(subject, "fullTokenInventory", "partial")
                self._set_source(subject, "etherscanV2", "available", "Token candidates read from paginated Etherscan V2 transfer history.")
                return ToolResult(
                    tool_name="getKnownTokenBalances",
                    source_status="partial",
                    data_coverage="transfer-derived-token-candidates",
                    output={"wallet": wallet, "balances": balances, "inventory": subject["_inventory"]},
                    limitation="Token inventory is derived from transfer history candidates and current RPC balance confirmations.",
                )

        if self.rpc and self.config.known_tokens:
            balances = self._known_token_rpc_balances(subject, self.config.known_tokens)
            subject["_balances"] = _merge_balances(subject.get("_balances", []), balances)
            normalizer = TokenInventoryNormalizer(wallet=wallet, chain_id=self.config.chain_id)
            subject["_inventory"] = normalizer.build_inventory(
                tokens=list(subject.get("_balances", [])),
                inventory_status="partial",
                source="configured_known_tokens_rpc_balanceOf",
            )
            self._set_completeness(subject, "knownTokenBalances", "partial")
            self._set_completeness(subject, "fullTokenInventory", "partial")
            return ToolResult(
                tool_name="getKnownTokenBalances",
                source_status="partial",
                data_coverage="known-token-only",
                output={"wallet": wallet, "balances": balances, "inventory": subject["_inventory"]},
                limitation="Configured known-token allowlist only; add MORALIS_API_KEY for full wallet inventory.",
            )

        return self._unavailable(
            subject,
            "getKnownTokenBalances",
            "Set MANTLE_KNOWN_TOKENS_JSON for RPC allowlist balances, or enable a Mantle-supported indexer. Moralis Data API is disabled by default for Mantle.",
        )

    def get_token_approvals(self, subject: dict[str, Any]) -> ToolResult:
        wallet = subject["wallet"]["address"]
        if not self.config.etherscan_v2_api_key:
            return self._unavailable(
                subject,
                "getTokenApprovals",
                "Set ETHERSCAN_V2_API_KEY or MANTLESCAN_API_KEY for indexed approval logs.",
            )
        try:
            page_result = self.etherscan.approval_logs_paginated(wallet, _history_options(subject))
            logs = page_result.rows
        except Exception as exc:
            self._set_source(subject, "etherscanV2", "partial", str(exc))
            return self._unavailable(subject, "getTokenApprovals", f"Etherscan V2 approval log error: {exc}")

        approvals = []
        seen: set[tuple[str, str]] = set()
        for log in logs:
            token_address = str(log.get("address", "")).lower()
            topics = log.get("topics") or []
            if len(topics) < 3 or not ADDRESS_PATTERN.match(token_address):
                continue
            spender = _address_from_topic(str(topics[2]))
            key = (token_address, spender)
            if key in seen:
                continue
            seen.add(key)
            event_allowance = _hex_to_int(str(log.get("data", "0x0")))
            active_allowance = event_allowance
            active_status = "event_value_only"
            allowance_confirmed = False
            if self.rpc:
                try:
                    active_allowance = self.rpc.erc20_allowance(token_address, wallet, spender)
                    active_status = "confirmed_by_rpc_allowance"
                    allowance_confirmed = True
                    self._set_completeness(subject, "activeAllowanceConfirmation", "available")
                except Exception:
                    self._set_completeness(subject, "activeAllowanceConfirmation", "partial")
            evidence_id = f"ev_live_approval_{stable_hash({'token': token_address, 'spender': spender})[2:14]}"
            block_number = _optional_int(log.get("blockNumber"))
            tx_hash = log.get("transactionHash")
            token_symbol = _symbol_for_token(subject, token_address) or token_address[:10]
            approval = {
                "approvalId": f"approval_live_{stable_hash({'token': token_address, 'spender': spender, 'tx': tx_hash})[2:14]}",
                "token": token_symbol,
                "tokenAddress": token_address,
                "owner": wallet,
                "spender": spender,
                "spenderLabel": None,
                "eventAllowanceRaw": str(event_allowance),
                "currentAllowanceRaw": str(active_allowance),
                "allowanceRaw": str(active_allowance),
                "allowanceConfirmed": allowance_confirmed,
                "allowanceUsd": 0,
                "isUnlimited": active_allowance >= UINT256_MAX // 2,
                "isActive": active_allowance > 0,
                "blockNumber": block_number,
                "txHash": tx_hash,
                "observedAt": _timestamp_from_row(log),
                "source": "etherscan_v2_logs_rpc_allowance",
                "dataCoverage": "indexed_approval_logs",
                "evidenceId": evidence_id,
            }
            approvals.append(approval)
            self._add_evidence(
                subject,
                evidence_id=evidence_id,
                evidence_type="approval",
                claim_text="An ERC20 approval event was found and active allowance was checked when RPC was available.",
                source="Etherscan V2",
                endpoint="logs:getLogs Approval + ERC20.allowance",
                raw_data={
                    "tokenAddress": token_address,
                    "spender": spender,
                    "eventAllowanceRaw": str(event_allowance),
                    "activeAllowanceRaw": str(active_allowance),
                    "activeStatus": active_status,
                    "allowanceConfirmed": allowance_confirmed,
                    "txHash": log.get("transactionHash"),
                },
                tx_hash=tx_hash,
                allowance_confirmed=allowance_confirmed,
                timestamp=approval["observedAt"],
                data_quality="fresh" if active_status == "confirmed_by_rpc_allowance" else "stale",
                limitation="Historical approval events are not current risk unless allowance is still active.",
            )

        subject["_approvals"] = approvals
        subject["_history"]["approvalHistory"] = {
            "status": "available",
            "items": approvals,
            "pageInfo": page_result.page_info,
        }
        subject["_pageCoverage"]["approvalHistory"] = page_result.page_info
        self._set_completeness(subject, "approvalEvents", "available")
        if not approvals and subject["dataCompleteness"]["activeAllowanceConfirmation"] == "unavailable":
            self._set_completeness(subject, "activeAllowanceConfirmation", "partial")
        self._set_source(subject, "etherscanV2", "available", "Approval logs read from Etherscan V2.")
        return ToolResult(
            tool_name="getTokenApprovals",
            source_status="available",
            data_coverage="indexed-approval-logs",
            output={"wallet": wallet, "approvals": approvals, "pageInfo": page_result.page_info},
            limitation="Approvals are normalized from indexed logs; active allowance confirmation uses Mantle RPC when available.",
        )

    def confirm_active_allowance(self, subject: dict[str, Any], token_address: str, spender: str) -> ToolResult:
        if not self.rpc:
            return self._unavailable(subject, "confirmActiveAllowance", "Mantle RPC is not configured.")
        allowance = self.rpc.erc20_allowance(token_address, subject["wallet"]["address"], spender)
        return ToolResult(
            tool_name="confirmActiveAllowance",
            source_status="available",
            data_coverage="live-rpc",
            output={
                "tokenAddress": token_address,
                "spender": spender,
                "isActive": allowance > 0,
                "allowanceRaw": str(allowance),
                "evidenceId": None,
            },
            limitation="A zero allowance means the approval is not considered current risk.",
        )

    def active_approvals(self, subject: dict[str, Any]) -> list[dict[str, Any]]:
        return [item for item in subject.get("_approvals", []) if item.get("isActive")]

    def get_spender_labels(self, subject: dict[str, Any]) -> ToolResult:
        self._set_completeness(subject, "spenderLabels", "partial")
        return ToolResult(
            tool_name="getSpenderLabels",
            source_status="partial",
            data_coverage="unknown-spenders",
            output={"labels": {}},
            limitation="P1 foundation has no trusted spender-label provider yet; unknown remains unknown.",
        )

    def get_transaction_count(self, subject: dict[str, Any]) -> ToolResult:
        if not self.config.etherscan_v2_api_key:
            return self._unavailable(subject, "getTransactionCount", "Set ETHERSCAN_V2_API_KEY for indexed transaction count.")
        try:
            transactions = self.etherscan.normal_transactions(subject["wallet"]["address"], limit=100)
        except Exception as exc:
            return self._unavailable(subject, "getTransactionCount", f"Etherscan V2 transaction error: {exc}")
        return ToolResult(
            tool_name="getTransactionCount",
            source_status="partial",
            data_coverage="recent-indexed-history",
            output={"wallet": subject["wallet"]["address"], "transactionCount": len(transactions)},
            limitation="Count is limited to the fetched indexed page.",
        )

    def get_transfer_logs(self, subject: dict[str, Any]) -> ToolResult:
        wallet = subject["wallet"]["address"]
        if self.config.moralis_history_available:
            try:
                rows = self.moralis.wallet_history(wallet, limit=_history_options(subject).page_size)
                transfers = self._transfers_from_moralis_history(subject, rows)
            except Exception as exc:
                self._set_source(subject, "moralis", "partial", str(exc))
            else:
                subject["_transfers"] = transfers
                subject["_history"]["transferHistory"] = {
                    "status": "available",
                    "items": transfers,
                    "pageInfo": {
                        "pageSize": _history_options(subject).page_size,
                        "fetchedPages": 1,
                        "hasMore": len(rows) >= _history_options(subject).page_size,
                        "fromBlock": _history_options(subject).from_block,
                        "toBlock": _history_options(subject).to_block,
                        "rowCount": len(transfers),
                        "sort": _history_options(subject).sort,
                        "provider": "moralis",
                    },
                }
                subject["_pageCoverage"]["transferHistory"] = subject["_history"]["transferHistory"]["pageInfo"]
                self._set_completeness(subject, "transferLogs", "available" if transfers else "partial")
                self._set_completeness(subject, "transactionHistory", "partial")
                self._set_source(subject, "moralis", "available", "Wallet history read from Moralis history switch.")
                return ToolResult(
                    tool_name="getTransferLogs",
                    source_status="available" if transfers else "partial",
                    data_coverage="moralis-wallet-history",
                    output={"wallet": wallet, "transfers": transfers, "pageInfo": subject["_history"]["transferHistory"]["pageInfo"]},
                    limitation="Moralis wallet history is provider-indexed and still bounded by request limits.",
                )
        if not self.config.etherscan_v2_api_key:
            return self._unavailable(
                subject,
                "getTransferLogs",
                "Set ETHERSCAN_V2_API_KEY or MANTLESCAN_API_KEY for indexed transfer history.",
            )
        try:
            page_result = self.etherscan.token_transfers_paginated(wallet, _history_options(subject))
            transfer_rows = page_result.rows
        except Exception as exc:
            self._set_source(subject, "etherscanV2", "partial", str(exc))
            return self._unavailable(subject, "getTransferLogs", f"Etherscan V2 transfer history error: {exc}")

        transfers = []
        for row in transfer_rows:
            if self.is_scan_deadline_expired(subject):
                self._set_source(subject, "etherscanV2", "partial", "Live scan deadline expired during transfer normalization.")
                break
            tx_hash = row.get("hash")
            if not tx_hash:
                continue
            evidence_id = f"ev_live_transfer_{stable_hash({'hash': row.get('hash'), 'token': row.get('contractAddress')})[2:14]}"
            incoming = str(row.get("to", "")).lower() == wallet
            counterparty = str(row.get("from" if incoming else "to", "")).lower()
            amount_raw = str(row.get("value") or "0")
            token_address = str(row.get("contractAddress", "")).lower()
            amount = _format_units(int(amount_raw), int(str(row.get("tokenDecimal") or "18")))
            transfer_type = "dust" if incoming and amount <= 0.000001 else "token_transfer"
            pattern = "lookalike_address_dust" if transfer_type == "dust" and _looks_similar(wallet, counterparty) else transfer_type
            transfer = {
                "transferId": f"transfer_live_{row.get('hash', '')[:12]}",
                "transferType": transfer_type,
                "tokenAddress": token_address,
                "token": row.get("tokenSymbol") or token_address[:10],
                "direction": "in" if incoming else "out",
                "amountRaw": amount_raw,
                "amount": str(amount),
                "counterparty": counterparty,
                "pattern": pattern,
                "riskLevel": "High" if "lookalike" in pattern else "Low",
                "blockNumber": _optional_int(row.get("blockNumber")),
                "txHash": tx_hash,
                "observedAt": _timestamp_from_row(row),
                "source": "etherscan_v2_tokentx",
                "evidenceId": evidence_id,
            }
            transfers.append(transfer)
            self._add_evidence(
                subject,
                evidence_id=evidence_id,
                evidence_type="transfer",
                claim_text="An indexed ERC20 transfer was found for this wallet.",
                source="Etherscan V2",
                endpoint="account:tokentx",
                raw_data=row,
                tx_hash=tx_hash,
                timestamp=_timestamp_from_row(row),
                data_quality="fresh",
                limitation="Transfer history is bounded by indexer pagination and API plan limits.",
            )

        subject["_transfers"] = transfers
        subject["_history"]["transferHistory"] = {
            "status": "available",
            "items": transfers,
            "pageInfo": page_result.page_info,
        }
        subject["_pageCoverage"]["transferHistory"] = page_result.page_info
        self._set_completeness(subject, "transferLogs", "available")
        self._set_completeness(subject, "transactionHistory", "partial")
        self._set_source(subject, "etherscanV2", "available", "Transfer history read from Etherscan V2.")
        return ToolResult(
            tool_name="getTransferLogs",
            source_status="available",
            data_coverage="indexed-token-history",
            output={"wallet": wallet, "transfers": transfers, "pageInfo": page_result.page_info},
            limitation="P1 fetches the first indexed page; extend pagination for production history completeness.",
        )

    def get_token_prices(self, subject: dict[str, Any]) -> ToolResult:
        prices = {
            item["symbol"]: item["priceUsd"]
            for item in subject.get("_balances", [])
            if item.get("priceUsd") is not None
        }
        return ToolResult(
            tool_name="getTokenPrices",
            source_status="available" if prices else "partial",
            data_coverage="balance-provider-prices",
            output={"prices": prices},
            limitation="Prices come from the balance provider when available; no standalone market oracle is configured yet.",
        )

    def get_token_security(self, subject: dict[str, Any]) -> ToolResult:
        token_addresses = [
            item["tokenAddress"]
            for item in subject.get("_balances", [])
            if item.get("tokenAddress") and item["tokenAddress"] != "native"
        ]
        if not token_addresses:
            return ToolResult(
                tool_name="getTokenSecurity",
                source_status="partial",
                data_coverage="no-token-inventory",
                output={"tokens": []},
                limitation="No token inventory is available yet; token security cannot be evaluated.",
            )
        try:
            security = self.goplus.token_security(token_addresses)
        except Exception as exc:
            self._set_source(subject, "goPlus", "partial", str(exc))
            return ToolResult(
                tool_name="getTokenSecurity",
                source_status="partial",
                data_coverage="token-inventory-without-security",
                output={"tokens": []},
                limitation=f"GoPlus token security error: {exc}",
            )

        tokens = []
        for item in subject.get("_balances", []):
            token_address = item.get("tokenAddress")
            if not token_address or token_address == "native":
                continue
            details = security.get(token_address.lower()) or security.get(token_address) or {}
            risk_flags = _goplus_risk_flags(details)
            security_signals = _goplus_security_signals(details)
            risk_status = "unknown"
            if details:
                risk_status = "risky" if risk_flags else "known"
            evidence_id = f"ev_live_security_{stable_hash({'token': token_address})[2:14]}"
            tokens.append(
                {
                    "symbol": item["symbol"],
                    "tokenAddress": token_address,
                    "status": risk_status,
                    "riskFlags": risk_flags,
                    "securitySignals": security_signals,
                    "evidenceId": evidence_id,
                    "evidenceIds": [evidence_id],
                }
            )
            self._add_evidence(
                subject,
                evidence_id=evidence_id,
                evidence_type="token_security",
                claim_text=_goplus_claim_text(item["symbol"], risk_flags, bool(details)),
                source="GoPlus",
                endpoint="token_security",
                raw_data={"details": details, "riskFlags": risk_flags, "securitySignals": security_signals},
                data_quality="fresh" if details else "missing",
                limitation="A clean token security response is a signal, not a guarantee.",
            )

        self._set_completeness(subject, "tokenSecurity", "available" if security else "partial")
        self._set_source(subject, "goPlus", "available", "Token security read from GoPlus.")
        return ToolResult(
            tool_name="getTokenSecurity",
            source_status="available" if security else "partial",
            data_coverage="token-security",
            output={"tokens": tokens},
            limitation="GoPlus security is evidence for review, not a proof of safety.",
        )

    def get_rwa_yield_exposure(self, subject: dict[str, Any]) -> ToolResult:
        balances = subject.get("_balances", [])
        valued = [item for item in balances if item.get("valueUsd", 0) > 0]
        total = sum(item["valueUsd"] for item in valued)
        if total <= 0:
            return ToolResult(
                tool_name="getRwaYieldExposure",
                source_status="partial",
                data_coverage="no-priced-balances",
                output={"wallet": subject["wallet"]["address"], "rwaYieldExposure": {}},
                limitation="Priced token balances are required to compute Mantle yield concentration.",
            )
        by_symbol = {item["symbol"]: item for item in valued}
        meth = by_symbol.get("mETH", {}).get("valueUsd", 0)
        cmeth = by_symbol.get("cmETH", {}).get("valueUsd", 0)
        musd = by_symbol.get("mUSD", {}).get("valueUsd", 0)
        usdy = by_symbol.get("USDY", {}).get("valueUsd", 0)
        evidence_ids = [
            item["evidenceId"]
            for item in [by_symbol.get("mETH"), by_symbol.get("cmETH"), by_symbol.get("mUSD"), by_symbol.get("USDY")]
            if item
        ]
        exposure = {
            "mETHPct": round(meth / total * 100, 2),
            "cmETHPct": round(cmeth / total * 100, 2),
            "mUSDPct": round(musd / total * 100, 2),
            "usdYPct": round(usdy / total * 100, 2),
            "liquidityWarning": (meth + cmeth) / total >= 0.5 if total else False,
            "evidenceIds": evidence_ids,
        }
        if evidence_ids:
            self._set_completeness(subject, "rwaYieldExposure", "available")
        return ToolResult(
            tool_name="getRwaYieldExposure",
            source_status="available" if evidence_ids else "partial",
            data_coverage="priced-balance-derived",
            output={"wallet": subject["wallet"]["address"], "rwaYieldExposure": exposure if evidence_ids else {}},
            limitation="Mantle yield exposure is derived from token symbols and priced balances.",
        )

    def _moralis_balances(self, subject: dict[str, Any]) -> list[dict[str, Any]]:
        rows = self.moralis.wallet_tokens(subject["wallet"]["address"])
        balances = []
        for row in rows:
            token_address = (row.get("token_address") or row.get("tokenAddress") or "").lower()
            symbol = str(row.get("symbol") or row.get("token_symbol") or token_address[:10] or "TOKEN")
            decimals = int(row.get("decimals") or 18)
            balance_raw = int(str(row.get("balance") or row.get("balanceRaw") or "0"))
            balance = _format_units(balance_raw, decimals)
            price = _optional_float(row.get("usd_price") or row.get("priceUsd"))
            value_usd = _optional_float(row.get("usd_value") or row.get("valueUsd"))
            if value_usd is None and price is not None:
                value_usd = round(balance * price, 2)
            evidence_id = f"ev_live_balance_{stable_hash({'token': token_address, 'symbol': symbol})[2:14]}"
            item = {
                "symbol": symbol,
                "tokenAddress": token_address or "native",
                "balanceRaw": str(balance_raw),
                "balance": balance,
                "priceUsd": price,
                "valueUsd": value_usd or 0.0,
                "evidenceId": evidence_id,
            }
            balances.append(item)
            self._add_evidence(
                subject,
                evidence_id=evidence_id,
                evidence_type="balance",
                claim_text=f"{symbol} balance was read from indexed wallet inventory.",
                source="Moralis",
                endpoint="wallets/{address}/tokens",
                raw_data=row,
                data_quality="fresh",
                limitation="Indexer inventory completeness depends on provider coverage and API plan.",
            )
        return balances

    def _known_token_rpc_balances(self, subject: dict[str, Any], tokens: tuple[KnownToken, ...]) -> list[dict[str, Any]]:
        balances = []
        for token in tokens:
            if self.is_scan_deadline_expired(subject):
                self._set_source(subject, "mantleRpc", "partial", "Live scan deadline expired during configured known-token balance checks.")
                break
            try:
                balance_raw = self.rpc.erc20_balance_of(token.token_address, subject["wallet"]["address"]) if self.rpc else 0
            except Exception:
                continue
            balance = _format_units(balance_raw, token.decimals)
            if balance_raw <= 0:
                continue
            evidence_id = f"ev_live_balance_{stable_hash({'token': token.token_address})[2:14]}"
            value_usd = round(balance * token.price_usd, 2) if token.price_usd is not None else 0.0
            item = {
                "symbol": token.symbol,
                "tokenAddress": token.token_address.lower(),
                "balanceRaw": str(balance_raw),
                "balance": balance,
                "priceUsd": token.price_usd,
                "valueUsd": value_usd,
                "evidenceId": evidence_id,
            }
            balances.append(item)
            self._add_evidence(
                subject,
                evidence_id=evidence_id,
                evidence_type="balance",
                claim_text=f"{token.symbol} configured-token balance was read from Mantle RPC.",
                source="Mantle RPC",
                endpoint="ERC20.balanceOf",
                raw_data={"tokenAddress": token.token_address, "balanceRaw": str(balance_raw)},
                data_quality="fresh",
                limitation="Configured known-token allowlist only.",
            )
        return balances

    def is_scan_deadline_expired(self, subject: dict[str, Any]) -> bool:
        deadline = subject.get("_scanDeadlineAt")
        return isinstance(deadline, (int, float)) and time.monotonic() >= deadline

    def deadline_unavailable(self, subject: dict[str, Any], tool_name: str) -> ToolResult:
        completeness_keys = {
            "getNativeBalance": ["nativeBalance"],
            "getKnownTokenBalances": ["knownTokenBalances", "fullTokenInventory"],
            "getTokenApprovals": ["approvalEvents", "activeAllowanceConfirmation"],
            "getTransferLogs": ["transferLogs", "transactionHistory"],
            "getTokenSecurity": ["tokenSecurity"],
            "getRwaYieldExposure": ["rwaYieldExposure"],
        }
        source_keys = {
            "getNativeBalance": ["mantleRpc"],
            "getKnownTokenBalances": ["mantleRpc", "moralis", "etherscanV2"],
            "getTokenApprovals": ["mantleRpc", "etherscanV2"],
            "getTransferLogs": ["moralis", "etherscanV2"],
            "getTokenSecurity": ["goPlus"],
        }
        for key in completeness_keys.get(tool_name, []):
            if subject["dataCompleteness"].get(key) == "unavailable":
                continue
            subject["dataCompleteness"][key] = "partial"
        for source_name in source_keys.get(tool_name, []):
            current = subject["sourceAvailability"].get(source_name, {})
            if current.get("status") == "unavailable":
                continue
            self._set_source(subject, source_name, "partial", "Live scan deadline expired before this source completed.")
        return self._unavailable(
            subject,
            tool_name,
            "Live scan deadline expired; unavailable means unknown, not safe.",
        )

    def _unavailable(self, subject: dict[str, Any], tool_name: str, limitation: str) -> ToolResult:
        return ToolResult(
            tool_name=tool_name,
            source_status="unavailable",
            data_coverage="missing",
            output={"wallet": subject["wallet"]["address"]},
            limitation=limitation,
        )

    def _set_completeness(self, subject: dict[str, Any], key: str, value: str) -> None:
        subject["dataCompleteness"][key] = value

    def _set_source(self, subject: dict[str, Any], source_name: str, status: str, limitation: str) -> None:
        subject["sourceAvailability"][source_name] = {"status": status, "limitation": limitation}

    def _add_evidence(
        self,
        subject: dict[str, Any],
        *,
        evidence_id: str,
        evidence_type: str,
        claim_text: str,
        source: str,
        endpoint: str,
        raw_data: dict[str, Any],
        data_quality: str,
        limitation: str | None = None,
        tx_hash: str | None = None,
        allowance_confirmed: bool | None = None,
        timestamp: str | None = None,
    ) -> None:
        if any(item["evidenceId"] == evidence_id for item in subject["evidence"]):
            return
        subject["evidence"].append(
            {
                "evidenceId": evidence_id,
                "type": evidence_type,
                "claimText": claim_text,
                "source": source,
                "endpoint": endpoint,
                "rawData": raw_data,
                "txHash": tx_hash,
                "allowanceConfirmed": allowance_confirmed,
                "timestamp": timestamp or datetime.now(UTC).isoformat(),
                "dataQuality": data_quality,
                "limitation": limitation,
            }
        )

    def _transfers_from_moralis_history(self, subject: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        transfers: list[dict[str, Any]] = []
        wallet = subject["wallet"]["address"]
        for row in rows:
            for transfer_row in _flatten_moralis_transfers(row):
                tx_hash = transfer_row.get("hash") or transfer_row.get("transaction_hash") or row.get("hash")
                if not tx_hash:
                    continue
                token_address = str(
                    transfer_row.get("tokenAddress")
                    or transfer_row.get("token_address")
                    or transfer_row.get("contractAddress")
                    or ""
                ).lower()
                if token_address and not ADDRESS_PATTERN.match(token_address):
                    continue
                incoming = str(transfer_row.get("to", "")).lower() == wallet
                counterparty = str(transfer_row.get("from" if incoming else "to", "")).lower()
                evidence_id = f"ev_live_transfer_{stable_hash({'hash': tx_hash, 'token': token_address})[2:14]}"
                transfer = {
                    "transferId": f"transfer_live_{str(tx_hash)[:12]}",
                    "transferType": "token_transfer",
                    "tokenAddress": token_address,
                    "token": transfer_row.get("tokenSymbol") or transfer_row.get("symbol") or token_address[:10],
                    "direction": "in" if incoming else "out",
                    "amountRaw": str(transfer_row.get("value") or transfer_row.get("amountRaw") or "0"),
                    "amount": str(transfer_row.get("amount") or transfer_row.get("value") or "0"),
                    "counterparty": counterparty,
                    "pattern": "token_transfer",
                    "riskLevel": "Low",
                    "blockNumber": _optional_int(transfer_row.get("blockNumber") or transfer_row.get("block_number")),
                    "txHash": tx_hash,
                    "observedAt": _timestamp_from_row(transfer_row) or _timestamp_from_row(row),
                    "source": "moralis_wallet_history",
                    "evidenceId": evidence_id,
                }
                transfers.append(transfer)
                self._add_evidence(
                    subject,
                    evidence_id=evidence_id,
                    evidence_type="transfer",
                    claim_text="A Moralis indexed wallet-history transfer was found for this wallet.",
                    source="Moralis",
                    endpoint="wallets/{address}/history",
                    raw_data=transfer_row,
                    tx_hash=tx_hash,
                    timestamp=transfer["observedAt"],
                    data_quality="fresh",
                    limitation="Moralis wallet history is bounded by provider pagination and plan limits.",
                )
        return transfers


def _hex_to_int(value: Any) -> int:
    if value is None:
        return 0
    text = str(value)
    if text.startswith("0x"):
        return int(text, 16)
    return int(text)


def _format_units(value: int, decimals: int) -> float:
    return round(value / (10**decimals), 8)


def _abi_address(address: str) -> str:
    return address.lower().replace("0x", "").rjust(64, "0")


def _topic_address(address: str) -> str:
    return "0x" + _abi_address(address)


def _address_from_topic(topic: str) -> str:
    clean = topic.lower().replace("0x", "")
    return "0x" + clean[-40:]


def _optional_float(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    try:
        return int(str(value), 0)
    except (TypeError, ValueError):
        return None


def _timestamp_from_row(row: dict[str, Any]) -> str | None:
    raw = row.get("timeStamp") or row.get("timestamp")
    if raw in {None, ""}:
        return None
    try:
        return datetime.fromtimestamp(int(raw), tz=UTC).isoformat()
    except (TypeError, ValueError):
        return None


def _looks_similar(wallet: str, counterparty: str) -> bool:
    if not ADDRESS_PATTERN.match(counterparty):
        return False
    return wallet[:8] == counterparty[:8] or wallet[-6:] == counterparty[-6:]


def _goplus_flags(details: dict[str, Any]) -> bool:
    return bool(_goplus_risk_flags(details))


def _goplus_risk_flags(details: dict[str, Any]) -> list[str]:
    risky_keys = {
        "is_honeypot",
        "is_blacklisted",
        "is_in_dex",
        "cannot_sell_all",
        "hidden_owner",
        "is_proxy",
        "is_mintable",
        "trading_cooldown",
        "transfer_pausable",
        "is_anti_whale",
        "personal_slippage_modifiable",
        "external_call",
        "selfdestruct",
        "is_airdrop_scam",
    }
    flags = []
    for key in risky_keys:
        if str(details.get(key, "0")) == "1":
            flags.append(key)
    return sorted(flags)


def _goplus_security_signals(details: dict[str, Any]) -> dict[str, Any]:
    signal_keys = [
        "is_open_source",
        "is_proxy",
        "is_mintable",
        "owner_address",
        "holder_count",
        "total_supply",
        "token_name",
        "token_symbol",
    ]
    return {key: details.get(key) for key in signal_keys if key in details}


def _goplus_claim_text(symbol: str, risk_flags: list[str], has_details: bool) -> str:
    if risk_flags:
        return f"GoPlus returned advisory risk flags for {symbol}: {', '.join(risk_flags)}."
    if has_details:
        return f"GoPlus returned no configured risk flags for {symbol}; this is an advisory signal only."
    return f"GoPlus did not return token-security details for {symbol}."


def _flatten_moralis_transfers(row: dict[str, Any]) -> list[dict[str, Any]]:
    nested_keys = ("erc20_transfers", "transfers", "token_transfers")
    flattened: list[dict[str, Any]] = []
    for key in nested_keys:
        value = row.get(key)
        if isinstance(value, list):
            flattened.extend(item for item in value if isinstance(item, dict))
    if not flattened:
        flattened.append(row)
    return flattened


def _symbol_for_token(subject: dict[str, Any], token_address: str) -> str | None:
    token_address = token_address.lower()
    for item in subject.get("_balances", []):
        if item.get("tokenAddress", "").lower() == token_address:
            return item.get("symbol")
    return None


def _history_options(subject: dict[str, Any]) -> HistoryPageOptions:
    options = subject.get("_historyOptions")
    if isinstance(options, HistoryPageOptions):
        return options
    return HistoryPageOptions()


def _merge_balances(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_address = {item["tokenAddress"]: item for item in existing}
    for item in incoming:
        by_address[item["tokenAddress"]] = item
    return list(by_address.values())
