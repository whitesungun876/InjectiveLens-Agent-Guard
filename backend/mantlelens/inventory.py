from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .hashutil import stable_hash


@dataclass(frozen=True)
class InventoryOptions:
    include_native: bool = True
    include_erc20: bool = True
    include_zero_balances: bool = False
    max_token_candidates: int = 250

    def __post_init__(self) -> None:
        if self.max_token_candidates < 1 or self.max_token_candidates > 1000:
            raise ValueError("max_token_candidates must be between 1 and 1000")


@dataclass(frozen=True)
class HistoryPageOptions:
    page_size: int = 100
    max_pages: int = 3
    from_block: int = 0
    to_block: str | int = "latest"
    sort: str = "desc"

    def __post_init__(self) -> None:
        if self.page_size < 10 or self.page_size > 1000:
            raise ValueError("page_size must be between 10 and 1000")
        if self.max_pages < 1 or self.max_pages > 10:
            raise ValueError("max_pages must be between 1 and 10")
        if self.from_block < 0:
            raise ValueError("from_block must be >= 0")
        if self.sort not in {"asc", "desc"}:
            raise ValueError("sort must be asc or desc")

    def pages(self) -> range:
        return range(1, self.max_pages + 1)

    def page_info(self, *, fetched_pages: int, last_page_count: int, row_count: int) -> dict[str, Any]:
        return {
            "pageSize": self.page_size,
            "fetchedPages": fetched_pages,
            "hasMore": fetched_pages == self.max_pages and last_page_count >= self.page_size,
            "fromBlock": self.from_block,
            "toBlock": self.to_block,
            "rowCount": row_count,
            "sort": self.sort,
        }


@dataclass(frozen=True)
class PaginatedHistoryResult:
    rows: list[dict[str, Any]]
    page_info: dict[str, Any]


class TokenInventoryNormalizer:
    def __init__(
        self,
        *,
        wallet: str,
        chain_id: int,
        options: InventoryOptions | None = None,
    ) -> None:
        self.wallet = wallet.lower()
        self.chain_id = chain_id
        self.options = options or InventoryOptions()

    def token_candidates_from_transfer_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        candidates: dict[str, dict[str, Any]] = {}
        for row in rows:
            token_address = _lower_address(row.get("contractAddress") or row.get("tokenAddress"))
            if not token_address:
                continue
            block_number = _optional_int(row.get("blockNumber"))
            current = candidates.get(token_address)
            if current is None:
                current = {
                    "tokenAddress": token_address,
                    "symbol": str(row.get("tokenSymbol") or row.get("symbol") or token_address[:10]),
                    "name": row.get("tokenName") or row.get("name"),
                    "decimals": _optional_int(row.get("tokenDecimal") or row.get("decimals")) or 18,
                    "firstSeenBlock": block_number,
                    "lastSeenBlock": block_number,
                    "candidateSource": "etherscan_v2_tokentx",
                    "sampleTxHash": row.get("hash") or row.get("transactionHash"),
                    "rowCount": 0,
                }
                candidates[token_address] = current
            current["rowCount"] += 1
            if block_number is not None:
                first_seen = current.get("firstSeenBlock")
                last_seen = current.get("lastSeenBlock")
                current["firstSeenBlock"] = block_number if first_seen is None else min(first_seen, block_number)
                current["lastSeenBlock"] = block_number if last_seen is None else max(last_seen, block_number)

        sorted_candidates = sorted(
            candidates.values(),
            key=lambda item: (item.get("lastSeenBlock") is not None, item.get("lastSeenBlock") or -1),
            reverse=True,
        )
        return sorted_candidates[: self.options.max_token_candidates]

    def native_balance_item(self, balance_raw: int, *, price_usd: float | None = None) -> dict[str, Any] | None:
        if balance_raw <= 0 and not self.options.include_zero_balances:
            return None
        balance = _format_units(balance_raw, 18)
        value_usd = round(balance * price_usd, 2) if price_usd is not None else 0.0
        evidence_id = f"ev_live_native_{self.wallet[2:10]}"
        return {
            "symbol": "MNT",
            "name": "Mantle",
            "tokenAddress": "native",
            "decimals": 18,
            "balanceRaw": str(balance_raw),
            "balance": balance,
            "priceUsd": price_usd,
            "valueUsd": value_usd,
            "firstSeenBlock": None,
            "lastSeenBlock": None,
            "candidateSource": "mantle_rpc_native",
            "balanceSource": "mantle_rpc_eth_getBalance",
            "securityStatus": "known",
            "isSpam": False,
            "evidenceId": evidence_id,
            "evidenceIds": [evidence_id],
        }

    def balance_item_from_candidate(
        self,
        candidate: dict[str, Any],
        *,
        balance_raw: int,
        price_usd: float | None = None,
        balance_source: str = "mantle_rpc_balanceOf",
        security_status: str = "unknown",
    ) -> dict[str, Any] | None:
        if balance_raw <= 0 and not self.options.include_zero_balances:
            return None
        decimals = int(candidate.get("decimals") or 18)
        balance = _format_units(balance_raw, decimals)
        value_usd = round(balance * price_usd, 2) if price_usd is not None else 0.0
        token_address = str(candidate["tokenAddress"]).lower()
        evidence_id = f"ev_live_balance_{stable_hash({'token': token_address, 'wallet': self.wallet})[2:14]}"
        return {
            "symbol": candidate.get("symbol") or token_address[:10],
            "name": candidate.get("name"),
            "tokenAddress": token_address,
            "decimals": decimals,
            "balanceRaw": str(balance_raw),
            "balance": balance,
            "priceUsd": price_usd,
            "valueUsd": value_usd,
            "firstSeenBlock": candidate.get("firstSeenBlock"),
            "lastSeenBlock": candidate.get("lastSeenBlock"),
            "candidateSource": candidate.get("candidateSource", "unknown"),
            "balanceSource": balance_source,
            "securityStatus": security_status,
            "isSpam": False,
            "evidenceId": evidence_id,
            "evidenceIds": [evidence_id],
        }

    def build_inventory(
        self,
        *,
        tokens: list[dict[str, Any]],
        inventory_status: str,
        source: str,
    ) -> dict[str, Any]:
        token_count = len(tokens)
        priced = [item for item in tokens if item.get("priceUsd") is not None]
        total_value_usd = round(sum(float(item.get("valueUsd") or 0) for item in tokens), 2)
        return {
            "wallet": self.wallet,
            "chainId": self.chain_id,
            "inventoryStatus": inventory_status,
            "totalValueUsd": total_value_usd,
            "tokenCount": token_count,
            "pricedTokenCount": len(priced),
            "unpricedTokenCount": token_count - len(priced),
            "source": source,
            "tokens": tokens,
        }


def dedupe_rows(rows: list[dict[str, Any]], *, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    deduped: list[dict[str, Any]] = []
    for row in rows:
        key = tuple(row.get(name) for name in keys)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _format_units(value: int, decimals: int) -> float:
    return round(value / (10**decimals), 8)


def _lower_address(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).lower()
    if text.startswith("0x") and len(text) == 42:
        return text
    return None


def _optional_int(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    try:
        return int(str(value), 0)
    except (TypeError, ValueError):
        return None
