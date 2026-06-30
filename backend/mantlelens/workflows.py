from __future__ import annotations

from typing import Any

from .adapters import FixtureWalletAdapter
from .alerts import ALERT_STORE, InMemoryAlertStore
from .analytics import EVENTS
from .explain import rule_based_explanation
from .evidence import evidence_binding_report
from .hashutil import stable_hash
from .history_store import ASSESSMENT_HISTORY_STORE, InMemoryAssessmentHistoryStore
from .ledger import LEDGER, InMemoryLedger
from .policy import PolicyEngine
from .risk import evaluate_wallet_risk
from .simulation import simulate_approval_revoke, simulate_portfolio_adjustment
from .trace import TraceRecorder
from .trend import TREND_STORE, InMemoryTrendStore


class WorkflowError(RuntimeError):
    pass


class WalletGuardRunner:
    """Runs the Day 5/6 deterministic agent workflow."""

    def __init__(
        self,
        adapter: Any | None = None,
        policy: PolicyEngine | None = None,
        trace: TraceRecorder | None = None,
        ledger: InMemoryLedger | None = None,
        trend_store: InMemoryTrendStore | None = None,
        alert_store: InMemoryAlertStore | None = None,
        history_store: InMemoryAssessmentHistoryStore | None = None,
    ) -> None:
        self.adapter = adapter or FixtureWalletAdapter()
        self.policy = policy or PolicyEngine()
        self.trace = trace or TraceRecorder()
        self.ledger = ledger or LEDGER
        self.trend_store = trend_store or TREND_STORE
        self.alert_store = alert_store or ALERT_STORE
        self.history_store = history_store or ASSESSMENT_HISTORY_STORE
        self.state = "INIT"

    def scan_wallet(
        self,
        *,
        fixture_id: str = "high_risk_wallet",
        wallet_address: str | None = None,
        history_options: Any | None = None,
        include_explanation: bool = True,
        benchmark_case: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._transition("DATA_GATHERING", "ScanWorkflow", "Wallet input accepted")
        EVENTS.record(
            "scan_started",
            run_id=self.trace.run_id,
            trace_id=self.trace.trace_id,
            wallet_hash="pending",
            state=self.state,
            properties={
                "fixtureId": fixture_id,
                "walletAddressProvided": bool(wallet_address),
                "adapter": self.adapter.__class__.__name__,
                "historyOptions": _option_summary(history_options),
            },
        )
        raw_scan = self._scan_workflow(
            fixture_id=fixture_id,
            wallet_address=wallet_address,
            history_options=history_options,
        )

        if _has_partial_data(raw_scan):
            self._transition("PARTIAL_OR_UNKNOWN", "ScanWorkflow", "Partial scan detected")
            self._transition("RISK_EVALUATING", "AssessmentWorkflow", "Partial assessment allowed")
        else:
            self._transition("RISK_EVALUATING", "AssessmentWorkflow", "Minimum scan package ready")

        risk_package = self._assessment_workflow(raw_scan)
        risk_package["assessment"]["fixtureId"] = raw_scan.get("fixtureId") or fixture_id
        if benchmark_case:
            risk_package["assessment"]["benchmarkCase"] = {
                "id": benchmark_case.get("id"),
                "label": benchmark_case.get("label"),
            }
        self._transition("EVIDENCE_BINDING", "AssessmentWorkflow", "Risk assessment produced")
        self._transition("EXPLAINING", "ExplanationWorkflow", "Evidence binding validated")

        explanation = None
        if include_explanation:
            explanation = self._explanation_workflow(
                risk_package["assessment"],
                risk_package["evidenceBundle"]["evidence"],
            )
        coverage = {
            "dataStatus": risk_package["assessment"]["dataStatus"],
            "dataCompleteness": raw_scan["dataCompleteness"],
            "sourceAvailability": raw_scan["sourceAvailability"],
            "pageCoverage": raw_scan.get("pageCoverage", {}),
            "missingDataIsSafe": False,
        }
        inventory = raw_scan.get("inventory") or _inventory_from_tool_outputs(raw_scan)
        history = raw_scan.get("history") or _history_from_tool_outputs(raw_scan)
        integrity = _integrity_report(
            risk_package["assessment"],
            risk_package["evidenceBundle"],
            coverage,
            inventory,
            history,
        )
        self._transition("SIMULATION_READY", "ExplanationWorkflow", "Fallback explanation ready")
        trend = self._trend_workflow(
            risk_package["assessment"],
            risk_package["evidenceBundle"],
        )
        history_record = self._history_workflow(
            risk_package["assessment"],
            risk_package["evidenceBundle"],
            coverage,
            inventory,
            history,
        )
        monitoring_trend = self.history_store.trend(
            address=risk_package["assessment"].get("wallet", {}).get("address"),
            wallet_hash=risk_package["assessment"].get("wallet", {}).get("walletHash"),
            chain_id=risk_package["assessment"].get("chainId"),
            mode=risk_package["assessment"].get("dataMode"),
        )
        alerts = self._alerts_workflow(
            risk_package["assessment"],
            risk_package["evidenceBundle"],
            coverage,
            inventory,
            history,
            monitoring_trend,
        )

        return {
            "assessment": risk_package["assessment"],
            "evidenceBundle": risk_package["evidenceBundle"],
            "explanation": explanation,
            "coverage": coverage,
            "inventory": inventory,
            "history": history,
            "toolOutputs": raw_scan["toolOutputs"],
            "trend": trend,
            "monitoringTrend": monitoring_trend,
            "assessmentHistoryRecord": history_record,
            "alerts": alerts,
            "integrity": integrity,
            "trace": self.trace.to_dict(),
        }

    def simulate(
        self,
        assessment: dict[str, Any],
        *,
        simulation_type: str,
        action_id: str | None = None,
    ) -> dict[str, Any]:
        if simulation_type == "approval_revoke_impact":
            simulation = simulate_approval_revoke(assessment, action_id=action_id)
        elif simulation_type == "portfolio_adjustment":
            simulation = simulate_portfolio_adjustment(assessment, action_id=action_id)
        else:
            raise WorkflowError(f"Unknown simulation type: {simulation_type}")
        self.trace.record(
            "simulation_completed",
            "Simulation-only diff completed",
            tool_name="simulatePortfolioAdjustment" if simulation_type == "portfolio_adjustment" else "simulateApprovalRevoke",
            details={
                "simulationId": simulation["simulationId"],
                "scoreDelta": simulation["scoreDelta"],
                "transactionCreated": simulation["transactionCreated"],
            },
        )
        EVENTS.record(
            "simulation_completed",
            run_id=self.trace.run_id,
            trace_id=self.trace.trace_id,
            wallet_hash=assessment["wallet"]["walletHash"],
            assessment_id=assessment["assessmentId"],
            state="SIMULATING",
            data_mode=assessment["dataMode"],
            properties={
                "simulationType": simulation_type,
                "scoreDelta": simulation["scoreDelta"],
                "transactionCreated": simulation["transactionCreated"],
            },
        )
        return {
            "simulation": simulation,
            "trace": self.trace.to_dict(),
        }

    def commit_assessment(
        self,
        assessment: dict[str, Any],
        *,
        idempotency_key: str,
        confirmation_received: bool = True,
        simulation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        decision = self.policy.allow_tool_call(
            "commitAssessment",
            stable_hash(
                {
                    "assessmentHash": assessment["assessmentHash"],
                    "idempotencyKey": idempotency_key,
                    "confirmationReceived": confirmation_received,
                }
            ),
            current_state="READY_TO_COMMIT",
            requires_confirmation=True,
            confirmation_received=confirmation_received,
            idempotency_key=idempotency_key,
        )
        self.trace.record(
            "policy_event",
            decision.reason,
            from_state="READY_TO_COMMIT",
            to_state="COMMIT_PENDING" if decision.allowed else "READY_TO_COMMIT",
            policy_decision=decision.decision,
            tool_name="commitAssessment",
        )
        if not decision.allowed:
            raise WorkflowError(decision.reason)
        record = self.ledger.commit_assessment(
            assessment,
            idempotency_key=idempotency_key,
            trace_id=self.trace.trace_id,
            simulation=simulation,
        )
        self.history_store.attach_commit(record)
        self.trace.record(
            "assessment_commit_status_changed",
            "Assessment record persisted",
            from_state="COMMIT_PENDING",
            to_state="COMMITTED",
            policy_decision="allow",
            tool_name="commitAssessment",
            details={
                "assessmentHash": record["assessmentHash"],
                "assessmentTx": record["assessmentTx"],
                "status": record["status"],
            },
        )
        EVENTS.record(
            "assessment_commit_status_changed",
            run_id=self.trace.run_id,
            trace_id=self.trace.trace_id,
            wallet_hash=assessment["wallet"]["walletHash"],
            assessment_id=assessment["assessmentId"],
            state="COMMITTED",
            data_mode=assessment["dataMode"],
            properties={
                "status": record["status"],
                "assessmentHash": record["assessmentHash"],
                "assessmentTx": record["assessmentTx"],
            },
        )
        return {
            "record": record,
            "trace": self.trace.to_dict(),
        }

    def simulate_commit_policy_check(
        self,
        *,
        assessment_hash: str,
        confirmation_received: bool,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        current_state = "READY_TO_COMMIT"
        decision = self.policy.allow_tool_call(
            "commitAssessment",
            stable_hash(
                {
                    "assessmentHash": assessment_hash,
                    "confirmationReceived": confirmation_received,
                    "idempotencyKey": idempotency_key,
                }
            ),
            current_state=current_state,
            requires_confirmation=True,
            confirmation_received=confirmation_received,
            idempotency_key=idempotency_key,
        )
        self.trace.record(
            "policy_event",
            decision.reason,
            from_state=current_state,
            to_state="COMMIT_PENDING" if decision.allowed else current_state,
            policy_decision=decision.decision,
            tool_name="commitAssessment",
        )
        return decision.to_dict()

    def _scan_workflow(
        self,
        *,
        fixture_id: str,
        wallet_address: str | None,
        history_options: Any | None,
    ) -> dict[str, Any]:
        try:
            fixture = self.adapter.load_scan_subject(
                fixture_id=fixture_id,
                wallet_address=wallet_address,
                history_options=history_options,
            )
        except AttributeError:
            fixture = self.adapter.load_fixture(fixture_id)
        except ValueError as exc:
            raise WorkflowError(str(exc)) from exc
        tool_results = {}
        tool_methods = [
            ("getNativeBalance", self.adapter.get_native_balance),
            ("getKnownTokenBalances", self.adapter.get_known_token_balances),
            ("getTokenApprovals", self.adapter.get_token_approvals),
            ("getTransferLogs", self.adapter.get_transfer_logs),
            ("getTokenPrices", self.adapter.get_token_prices),
            ("getTokenSecurity", self.adapter.get_token_security),
            ("getRwaYieldExposure", self.adapter.get_rwa_yield_exposure),
        ]
        for tool_name, method in tool_methods:
            deadline_checker = getattr(self.adapter, "is_scan_deadline_expired", None)
            deadline_fallback = getattr(self.adapter, "deadline_unavailable", None)
            if callable(deadline_checker) and deadline_checker(fixture):
                if not callable(deadline_fallback):
                    raise WorkflowError("Live scan deadline expired")
                result = deadline_fallback(fixture, tool_name)
                tool_results[tool_name] = result.to_dict()
                self.trace.record(
                    "tool_call_skipped",
                    "Live scan deadline expired before tool call",
                    tool_name=tool_name,
                    details={"deadlineExpired": True},
                )
                continue
            decision = self.policy.allow_tool_call(
                tool_name,
                stable_hash(
                    {
                        "fixtureId": fixture.get("fixtureId"),
                        "wallet": fixture.get("wallet", {}).get("address"),
                        "toolName": tool_name,
                        "historyOptions": _option_summary(history_options),
                    }
                ),
                current_state=self.state,
            )
            if not decision.allowed:
                self.trace.record(
                    "tool_call_blocked",
                    decision.reason,
                    policy_decision=decision.decision,
                    tool_name=tool_name,
                )
                raise WorkflowError(decision.reason)
            result = self.trace.timed_tool(tool_name, method, fixture)
            tool_results[tool_name] = result.to_dict()

        return {
            "fixtureId": fixture["fixtureId"],
            "wallet": fixture["wallet"],
            "chainId": fixture["chainId"],
            "dataMode": fixture["dataMode"],
            "dataCompleteness": fixture["dataCompleteness"],
            "sourceAvailability": fixture["sourceAvailability"],
            "toolOutputs": tool_results,
            "evidence": fixture.get("evidence", []),
            "inventory": fixture.get("_inventory"),
            "history": fixture.get("_history"),
            "pageCoverage": fixture.get("_pageCoverage", {}),
        }

    def _assessment_workflow(self, raw_scan: dict[str, Any]) -> dict[str, Any]:
        decision = self.policy.allow_tool_call(
            "evaluateWalletRisk",
            stable_hash({"fixtureId": raw_scan["fixtureId"]}),
            current_state=self.state,
        )
        if not decision.allowed:
            raise WorkflowError(decision.reason)
        package = evaluate_wallet_risk(raw_scan)
        assessment = package["assessment"]
        self.trace.record(
            "risk_evaluation_completed",
            "White-box risk engine completed",
            tool_name="evaluateWalletRisk",
            details={
                "walletRiskScore": package["assessment"]["walletRiskScore"],
                "riskLevel": package["assessment"]["riskLevel"],
                "dataStatus": package["assessment"]["dataStatus"],
            },
        )
        self.trace.record(
            "evidence_bundle_built",
            "Evidence bundle built",
            tool_name="buildEvidenceBundle",
            details={
                "evidenceBundleHash": package["evidenceBundle"]["evidenceBundleHash"],
                "evidenceCount": package["evidenceBundle"]["evidenceCount"],
                "orphanClaimCount": 0,
            },
        )
        EVENTS.record(
            "risk_evaluation_completed",
            run_id=self.trace.run_id,
            trace_id=self.trace.trace_id,
            wallet_hash=assessment["wallet"]["walletHash"],
            assessment_id=assessment["assessmentId"],
            state=self.state,
            data_mode=assessment["dataMode"],
            properties={
                "walletRiskScore": assessment["walletRiskScore"],
                "riskLevel": assessment["riskLevel"],
                "dataConfidence": assessment["dataConfidence"],
            },
        )
        EVENTS.record(
            "evidence_bundle_built",
            run_id=self.trace.run_id,
            trace_id=self.trace.trace_id,
            wallet_hash=assessment["wallet"]["walletHash"],
            assessment_id=assessment["assessmentId"],
            state=self.state,
            data_mode=assessment["dataMode"],
            properties={
                "evidenceCount": package["evidenceBundle"]["evidenceCount"],
                "evidenceBundleHash": package["evidenceBundle"]["evidenceBundleHash"],
                "orphanClaimCount": 0,
            },
        )
        return package

    def _explanation_workflow(
        self,
        assessment: dict[str, Any],
        evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        decision = self.policy.allow_tool_call(
            "explainAssessment",
            stable_hash({"assessmentId": assessment["assessmentId"], "mode": "rule_fallback"}),
            current_state=self.state,
        )
        if not decision.allowed:
            raise WorkflowError(decision.reason)
        explanation = rule_based_explanation(
            assessment,
            evidence,
            fallback_reason="Day 5 deterministic fallback before LLM integration",
        )
        self.trace.record(
            "explanation_completed",
            "Rule fallback explanation completed",
            tool_name="explainAssessment",
            details={
                "mode": explanation["mode"],
                "claimGuardPassed": explanation["claimGuardPassed"],
            },
        )
        EVENTS.record(
            "explanation_completed",
            run_id=self.trace.run_id,
            trace_id=self.trace.trace_id,
            wallet_hash=assessment["wallet"]["walletHash"],
            assessment_id=assessment["assessmentId"],
            state=self.state,
            data_mode=assessment["dataMode"],
            properties={
                "mode": explanation["mode"],
                "claimGuardPassed": explanation["claimGuardPassed"],
            },
        )
        return explanation

    def _trend_workflow(
        self,
        assessment: dict[str, Any],
        evidence_bundle: dict[str, Any],
    ) -> dict[str, Any]:
        trend = self.trend_store.record_assessment(assessment, evidence_bundle)
        self.trace.record(
            "risk_trend_recorded",
            "Risk trend point recorded",
            tool_name="recordRiskTrend",
            details={
                "trendStatus": trend["status"],
                "pointCount": trend["pointCount"],
                "walletHash": trend["walletHash"],
            },
        )
        EVENTS.record(
            "risk_trend_recorded",
            run_id=self.trace.run_id,
            trace_id=self.trace.trace_id,
            wallet_hash=assessment["wallet"]["walletHash"],
            assessment_id=assessment["assessmentId"],
            state=self.state,
            data_mode=assessment["dataMode"],
            properties={
                "trendStatus": trend["status"],
                "pointCount": trend["pointCount"],
                "currentAssessmentHash": assessment["assessmentHash"],
            },
        )
        return trend

    def _history_workflow(
        self,
        assessment: dict[str, Any],
        evidence_bundle: dict[str, Any],
        coverage: dict[str, Any],
        inventory: dict[str, Any] | None,
        history: dict[str, Any] | None,
    ) -> dict[str, Any]:
        record = self.history_store.record_scan(
            assessment=assessment,
            evidence_bundle=evidence_bundle,
            coverage=coverage,
            inventory=inventory,
            history=history,
        )
        self.trace.record(
            "assessment_history_recorded",
            "Assessment history record persisted",
            tool_name="recordAssessmentHistory",
            details={
                "historyRecordId": record["historyRecordId"],
                "walletHash": record["walletHash"],
                "mode": record["mode"],
                "chainId": record["chainId"],
            },
        )
        EVENTS.record(
            "assessment_history_recorded",
            run_id=self.trace.run_id,
            trace_id=self.trace.trace_id,
            wallet_hash=assessment["wallet"]["walletHash"],
            assessment_id=assessment["assessmentId"],
            state=self.state,
            data_mode=assessment["dataMode"],
            properties={
                "historyRecordId": record["historyRecordId"],
                "mode": record["mode"],
                "chainId": record["chainId"],
            },
        )
        return record

    def _alerts_workflow(
        self,
        assessment: dict[str, Any],
        evidence_bundle: dict[str, Any],
        coverage: dict[str, Any],
        inventory: dict[str, Any] | None,
        history: dict[str, Any] | None,
        trend: dict[str, Any],
    ) -> list[dict[str, Any]]:
        alerts = self.alert_store.evaluate(
            assessment=assessment,
            evidence_bundle=evidence_bundle,
            coverage=coverage,
            inventory=inventory,
            history=history,
            trend=trend,
        )
        self.trace.record(
            "alerts_evaluated",
            "Local alert rules evaluated",
            tool_name="evaluateAlerts",
            details={
                "alertCount": len(alerts),
                "openAlertTypes": [alert["alertType"] for alert in alerts],
            },
        )
        EVENTS.record(
            "alerts_evaluated",
            run_id=self.trace.run_id,
            trace_id=self.trace.trace_id,
            wallet_hash=assessment["wallet"]["walletHash"],
            assessment_id=assessment["assessmentId"],
            state=self.state,
            data_mode=assessment["dataMode"],
            properties={
                "alertCount": len(alerts),
                "openAlertTypes": [alert["alertType"] for alert in alerts],
                "sourceAssessmentHash": assessment["assessmentHash"],
            },
        )
        return alerts

    def _transition(self, to_state: str, workflow_name: str, message: str) -> None:
        decision = self.policy.allow_transition(self.state, to_state)
        self.trace.record(
            "agent_state_changed",
            message if decision.allowed else decision.reason,
            from_state=self.state,
            to_state=to_state,
            policy_decision=decision.decision,
            workflow_name=workflow_name,
        )
        if not decision.allowed:
            raise WorkflowError(decision.reason)
        self.state = to_state


def _has_partial_data(raw_scan: dict[str, Any]) -> bool:
    return any(
        value in {"partial", "unavailable", "not_supported_p0"}
        for value in raw_scan.get("dataCompleteness", {}).values()
    )


def _inventory_from_tool_outputs(raw_scan: dict[str, Any]) -> dict[str, Any] | None:
    tool_outputs = raw_scan.get("toolOutputs", {})
    balances = []
    native = (tool_outputs.get("getNativeBalance", {}).get("output") or {}).get("balance")
    if isinstance(native, dict):
        balances.append(native)
    balances.extend(
        item
        for item in (tool_outputs.get("getKnownTokenBalances", {}).get("output") or {}).get("balances", [])
        if isinstance(item, dict)
    )
    if not balances:
        return None
    return {
        "wallet": raw_scan.get("wallet", {}).get("address"),
        "chainId": raw_scan.get("chainId"),
        "inventoryStatus": raw_scan.get("dataCompleteness", {}).get("fullTokenInventory", "partial"),
        "totalValueUsd": round(sum(float(item.get("valueUsd") or 0) for item in balances), 2),
        "tokenCount": len(balances),
        "pricedTokenCount": sum(1 for item in balances if item.get("priceUsd") is not None),
        "unpricedTokenCount": sum(1 for item in balances if item.get("priceUsd") is None),
        "source": "tool_outputs_projection",
        "tokens": balances,
    }


def _history_from_tool_outputs(raw_scan: dict[str, Any]) -> dict[str, Any]:
    tool_outputs = raw_scan.get("toolOutputs", {})
    approvals = (tool_outputs.get("getTokenApprovals", {}).get("output") or {}).get("approvals", [])
    transfers = (tool_outputs.get("getTransferLogs", {}).get("output") or {}).get("transfers", [])
    return {
        "wallet": raw_scan.get("wallet", {}).get("address"),
        "chainId": raw_scan.get("chainId"),
        "approvalHistory": {
            "status": (tool_outputs.get("getTokenApprovals", {}) or {}).get("sourceStatus", "unavailable"),
            "items": approvals if isinstance(approvals, list) else [],
            "pageInfo": (tool_outputs.get("getTokenApprovals", {}).get("output") or {}).get("pageInfo"),
        },
        "transferHistory": {
            "status": (tool_outputs.get("getTransferLogs", {}) or {}).get("sourceStatus", "unavailable"),
            "items": transfers if isinstance(transfers, list) else [],
            "pageInfo": (tool_outputs.get("getTransferLogs", {}).get("output") or {}).get("pageInfo"),
        },
    }


def _integrity_report(
    assessment: dict[str, Any],
    evidence_bundle: dict[str, Any],
    coverage: dict[str, Any],
    inventory: dict[str, Any] | None,
    history: dict[str, Any] | None,
) -> dict[str, Any]:
    source_availability = coverage.get("sourceAvailability", {})
    data_completeness = coverage.get("dataCompleteness", {})
    partial_sources = sorted(
        name
        for name, source in source_availability.items()
        if isinstance(source, dict) and source.get("status") == "partial"
    )
    unavailable_sources = sorted(
        name
        for name, source in source_availability.items()
        if isinstance(source, dict) and source.get("status") == "unavailable"
    )
    source_failures = [
        {
            "source": name,
            "status": "partial",
            "limitation": source_availability.get(name, {}).get("limitation"),
        }
        for name in partial_sources
    ] + [
        {
            "source": name,
            "status": "source_failed",
            "limitation": source_availability.get(name, {}).get("limitation"),
        }
        for name in unavailable_sources
    ]
    incomplete_data = sorted(
        key
        for key, value in data_completeness.items()
        if value in {"partial", "unavailable", "not_supported_p0"}
    )
    binding = evidence_binding_report(assessment, evidence_bundle.get("evidence", []))
    detail_resolution = _detail_resolution(evidence_bundle.get("evidence", []), inventory, history)
    onchain_allowed = assessment.get("dataMode") == "live" and binding["status"] == "pass"
    return {
        "schemaVersion": "mantlelens.scan_integrity.v1",
        "evidenceBinding": {
            key: value
            for key, value in binding.items()
            if key != "knownEvidenceIds"
        },
        "sourceIntegrity": {
            "status": "partial" if source_failures or incomplete_data else "pass",
            "missingDataIsSafe": False,
            "partialSources": partial_sources,
            "unavailableSources": unavailable_sources,
            "sourceFailures": source_failures,
            "incompleteData": incomplete_data,
        },
        "detailResolution": detail_resolution,
        "topRiskEvidenceBound": binding["status"] == "pass",
        "commitEligibility": {
            "localRecordAllowed": binding["status"] == "pass",
            "onchainRecordAllowed": onchain_allowed,
            "reason": "live assessment with evidence-bound claims"
            if onchain_allowed
            else "on-chain commit requires live dataMode and evidence-bound claims",
        },
    }


def _detail_resolution(
    evidence_items: list[dict[str, Any]],
    inventory: dict[str, Any] | None,
    history: dict[str, Any] | None,
) -> dict[str, Any]:
    inventory_ids = _row_evidence_ids((inventory or {}).get("tokens", []))
    approval_ids = _row_evidence_ids(
        ((history or {}).get("approvalHistory") or {}).get("items", [])
    )
    transfer_ids = _row_evidence_ids(
        ((history or {}).get("transferHistory") or {}).get("items", [])
    )
    rows_by_panel = {
        "inventory": sorted(inventory_ids),
        "approvals": sorted(approval_ids),
        "transfers": sorted(transfer_ids),
    }
    unresolved: list[dict[str, str]] = []
    for evidence in evidence_items:
        evidence_id = evidence.get("evidenceId")
        evidence_type = evidence.get("type")
        if not evidence_id:
            continue
        if evidence_type in {"balance", "token_security", "rwa_yield"}:
            if evidence_id not in inventory_ids and evidence_type == "balance":
                unresolved.append({"evidenceId": evidence_id, "expectedPanel": "inventory"})
        elif evidence_type == "approval":
            if evidence_id not in approval_ids:
                unresolved.append({"evidenceId": evidence_id, "expectedPanel": "approvals"})
        elif evidence_type == "transfer":
            if evidence_id not in transfer_ids:
                unresolved.append({"evidenceId": evidence_id, "expectedPanel": "transfers"})
    return {
        "status": "fail" if unresolved else "pass",
        "rowsByPanel": rows_by_panel,
        "unresolvedEvidence": unresolved,
    }


def _row_evidence_ids(rows: Any) -> set[str]:
    ids: set[str] = set()
    if not isinstance(rows, list):
        return ids
    for row in rows:
        if not isinstance(row, dict):
            continue
        evidence_id = row.get("evidenceId")
        if evidence_id:
            ids.add(str(evidence_id))
        for value in row.get("evidenceIds") or []:
            ids.add(str(value))
    return ids


def _option_summary(options: Any | None) -> dict[str, Any] | None:
    if options is None:
        return None
    summary: dict[str, Any] = {}
    for name in ("page_size", "max_pages", "from_block", "to_block", "sort"):
        if hasattr(options, name):
            summary[name] = getattr(options, name)
    return summary or None
