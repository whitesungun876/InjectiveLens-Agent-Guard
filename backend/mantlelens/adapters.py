from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .fixtures import FixtureRepository


@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    source_status: str
    data_coverage: str
    output: dict[str, Any]
    limitation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "toolName": self.tool_name,
            "sourceStatus": self.source_status,
            "dataCoverage": self.data_coverage,
            "output": self.output,
            "limitation": self.limitation,
        }


class FixtureWalletAdapter:
    """Raw P0 wallet tools backed by Day 2 fixtures.

    This adapter is intentionally view-only. It models the shape and guardrails
    of real Mantle RPC / GoPlus / price tools while keeping Day 3 deterministic.
    """

    def __init__(self, repository: FixtureRepository | None = None) -> None:
        self.repository = repository or FixtureRepository()

    def load_scan_subject(
        self,
        *,
        fixture_id: str | None = None,
        wallet_address: str | None = None,
        history_options: Any | None = None,
    ) -> dict[str, Any]:
        return self.load_fixture(fixture_id or "high_risk_wallet")

    def load_fixture(self, fixture_id: str) -> dict[str, Any]:
        return self.repository.load_copy(fixture_id)

    def scan_raw(self, fixture_id: str) -> dict[str, Any]:
        fixture = self.load_fixture(fixture_id)
        return {
            "fixtureId": fixture["fixtureId"],
            "wallet": fixture["wallet"],
            "chainId": fixture["chainId"],
            "dataMode": fixture["dataMode"],
            "dataCompleteness": fixture["dataCompleteness"],
            "sourceAvailability": fixture["sourceAvailability"],
            "toolOutputs": {
                "getNativeBalance": self.get_native_balance(fixture).to_dict(),
                "getKnownTokenBalances": self.get_known_token_balances(fixture).to_dict(),
                "getTokenApprovals": self.get_token_approvals(fixture).to_dict(),
                "getTransferLogs": self.get_transfer_logs(fixture).to_dict(),
                "getTokenPrices": self.get_token_prices(fixture).to_dict(),
                "getTokenSecurity": self.get_token_security(fixture).to_dict(),
                "getRwaYieldExposure": self.get_rwa_yield_exposure(fixture).to_dict(),
            },
            "evidence": fixture.get("evidence", []),
        }

    def get_native_balance(self, fixture: dict[str, Any]) -> ToolResult:
        native = next((item for item in fixture.get("balances", []) if item["tokenAddress"] == "native"), None)
        status = fixture["dataCompleteness"]["nativeBalance"]
        return ToolResult(
            tool_name="getNativeBalance",
            source_status=status,
            data_coverage=self._coverage_for(fixture),
            output={"wallet": fixture["wallet"], "balance": native},
            limitation=fixture["sourceAvailability"].get("mantleRpc", {}).get("limitation"),
        )

    def get_known_token_balances(self, fixture: dict[str, Any]) -> ToolResult:
        balances = [item for item in fixture.get("balances", []) if item["tokenAddress"] != "native"]
        return ToolResult(
            tool_name="getKnownTokenBalances",
            source_status=fixture["dataCompleteness"]["knownTokenBalances"],
            data_coverage=self._coverage_for(fixture),
            output={"wallet": fixture["wallet"], "balances": balances},
            limitation="Known-token allowlist only; unknown wallet tokens require an indexer.",
        )

    def get_token_approvals(self, fixture: dict[str, Any]) -> ToolResult:
        approvals = fixture.get("approvals", [])
        return ToolResult(
            tool_name="getTokenApprovals",
            source_status=fixture["dataCompleteness"]["approvalEvents"],
            data_coverage=self._coverage_for(fixture),
            output={"wallet": fixture["wallet"], "approvals": approvals},
            limitation="Approval logs are followed by allowance confirmation before risk scoring.",
        )

    def confirm_active_allowance(
        self,
        fixture: dict[str, Any],
        token_address: str,
        spender: str,
    ) -> ToolResult:
        approval = next(
            (
                item
                for item in fixture.get("approvals", [])
                if item["tokenAddress"].lower() == token_address.lower()
                and item["spender"].lower() == spender.lower()
            ),
            None,
        )
        status = fixture["dataCompleteness"]["activeAllowanceConfirmation"]
        return ToolResult(
            tool_name="confirmActiveAllowance",
            source_status=status,
            data_coverage=self._coverage_for(fixture),
            output={
                "tokenAddress": token_address,
                "spender": spender,
                "isActive": bool(approval and approval.get("isActive")),
                "allowanceRaw": approval.get("allowanceRaw") if approval else "0",
                "evidenceId": approval.get("evidenceId") if approval else None,
            },
            limitation="A zero allowance means the approval is not considered current risk.",
        )

    def active_approvals(self, fixture: dict[str, Any]) -> list[dict[str, Any]]:
        return [item for item in fixture.get("approvals", []) if item.get("isActive")]

    def get_spender_labels(self, fixture: dict[str, Any]) -> ToolResult:
        labels = {
            item["spender"]: item.get("spenderLabel")
            for item in fixture.get("approvals", [])
            if item.get("spender")
        }
        return ToolResult(
            tool_name="getSpenderLabels",
            source_status=fixture["dataCompleteness"]["spenderLabels"],
            data_coverage=self._coverage_for(fixture),
            output={"labels": labels},
            limitation="Unavailable spender label is unknown, not safe.",
        )

    def get_transaction_count(self, fixture: dict[str, Any]) -> ToolResult:
        count = 3 if fixture["fixtureId"].startswith("low") else 24
        return ToolResult(
            tool_name="getTransactionCount",
            source_status="available",
            data_coverage=self._coverage_for(fixture),
            output={"wallet": fixture["wallet"], "transactionCount": count},
            limitation="Fixture value used for Day 3 harness only.",
        )

    def get_transfer_logs(self, fixture: dict[str, Any]) -> ToolResult:
        return ToolResult(
            tool_name="getTransferLogs",
            source_status=fixture["dataCompleteness"]["transferLogs"],
            data_coverage=self._coverage_for(fixture),
            output={"wallet": fixture["wallet"], "transfers": fixture.get("transfers", [])},
            limitation="Bounded recent logs over known tokens only.",
        )

    def get_token_prices(self, fixture: dict[str, Any]) -> ToolResult:
        prices = {
            item["symbol"]: item["priceUsd"]
            for item in fixture.get("balances", [])
            if item.get("priceUsd") is not None
        }
        status = fixture["sourceAvailability"].get("coinGecko", {}).get("status", "partial")
        return ToolResult(
            tool_name="getTokenPrices",
            source_status=status,
            data_coverage=self._coverage_for(fixture),
            output={"prices": prices},
            limitation="Price-only source; not APY, holder count, or security label.",
        )

    def get_token_security(self, fixture: dict[str, Any]) -> ToolResult:
        token_security = [
            {
                "symbol": item["symbol"],
                "tokenAddress": item["tokenAddress"],
                "status": "unknown" if item["symbol"] not in {"MNT", "USDC", "USDT", "mUSD", "mETH", "cmETH"} else "known",
                "evidenceId": item["evidenceId"],
            }
            for item in fixture.get("balances", [])
            if item["tokenAddress"] != "native"
        ]
        status = fixture["dataCompleteness"]["tokenSecurity"]
        return ToolResult(
            tool_name="getTokenSecurity",
            source_status=status,
            data_coverage=self._coverage_for(fixture),
            output={"tokens": token_security},
            limitation="GoPlus clean result is a signal, not a guarantee.",
        )

    def get_rwa_yield_exposure(self, fixture: dict[str, Any]) -> ToolResult:
        exposure = fixture.get("rwaYieldExposure", {})
        status = fixture["dataCompleteness"]["rwaYieldExposure"]
        return ToolResult(
            tool_name="getRwaYieldExposure",
            source_status=status,
            data_coverage=self._coverage_for(fixture),
            output={"wallet": fixture["wallet"], "rwaYieldExposure": exposure},
            limitation="mETH/cmETH are Mantle yield assets; P0 does not provide yield advice.",
        )

    def _coverage_for(self, fixture: dict[str, Any]) -> str:
        expected = fixture.get("expectedAssessment", {})
        if expected.get("dataCoverage"):
            return expected["dataCoverage"]
        completeness = fixture.get("dataCompleteness", {})
        if any(value == "partial" for value in completeness.values()):
            return "partial"
        if completeness.get("fullTokenInventory") == "not_supported_p0":
            return "known-token-only"
        return "full"
