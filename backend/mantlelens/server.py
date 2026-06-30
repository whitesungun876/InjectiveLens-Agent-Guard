from __future__ import annotations

import argparse
import json
import mimetypes
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .alerts import ALERT_STORE, InMemoryAlertStore
from .analytics import EVENTS
from .chain_targets import ChainTargetError, config_for_chain_target, resolve_chain_target
from .config import MantleLensConfig
from .enhancements import (
    build_social_share_card,
    detect_nft_approvals,
    enhancement_summary,
    evaluate_goplus_full_security,
    parse_defi_positions,
    prepare_manual_revoke,
    record_reputation_feedback,
    simulate_transaction,
)
from .explain import rule_based_explanation
from .fixtures import FixtureNotFoundError
from .history_store import (
    ASSESSMENT_HISTORY_STORE,
    InMemoryAssessmentHistoryStore,
    build_history_response,
)
from .inventory import HistoryPageOptions
from .ledger import LEDGER, InMemoryLedger
from .live_adapters import LiveWalletAdapter
from .llm_guard import guarded_explanation
from .onchain import (
    AssessmentReadbackVerifier,
    AssessmentRecorder,
    LocalOnlyAssessmentRecorder,
    OnchainReadbackError,
    build_assessment_commit_calldata,
)
from .policy import PolicyEngine
from .protocol import agent_card, agent_registration, mcp_call_response, mcp_list_response
from .trace import TraceRecorder
from .trend import TREND_STORE, InMemoryTrendStore
from .workflows import WalletGuardRunner, WorkflowError


ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = ROOT / "frontend"
REACT_DIST_DIR = ROOT / "frontend" / "app" / "dist"


class MantleLensRequestHandler(SimpleHTTPRequestHandler):
    server_version = "MantleLensHTTP/0.1"

    def log_message(self, format: str, *args: Any) -> None:
        if getattr(self.server, "quiet", False):
            return
        super().log_message(format, *args)

    def do_OPTIONS(self) -> None:
        self._send_empty(HTTPStatus.NO_CONTENT)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._send_json(
                {
                    "status": "ok",
                    "service": "mantlelens-wallet-guard",
                    "mode": "demo+p1-live-ready",
                    "day": "11",
                }
            )
            return
        if parsed.path == "/api/provider/status":
            self._send_json(MantleLensConfig.from_env().public_provider_status())
            return
        if parsed.path in {"/agent-registration.json", "/.well-known/agent-registration.json"}:
            self._send_json(agent_registration(self._base_url()))
            return
        if parsed.path == "/.well-known/agent-card.json":
            self._send_json(agent_card(self._base_url()))
            return
        if parsed.path == "/api/benchmark":
            self._handle_benchmark(parsed.query)
            return
        if parsed.path == "/api/wallet/balances":
            self._handle_wallet_projection(parsed.query, "balances")
            return
        if parsed.path == "/api/wallet/approvals":
            self._handle_wallet_projection(parsed.query, "approvals")
            return
        if parsed.path == "/api/wallet/transfers":
            self._handle_wallet_projection(parsed.query, "transfers")
            return
        if parsed.path == "/api/wallet/exposure":
            self._handle_wallet_projection(parsed.query, "exposure")
            return
        if parsed.path == "/api/wallet/data-availability":
            self._handle_wallet_projection(parsed.query, "data_availability")
            return
        if parsed.path == "/api/wallet/history":
            self._handle_wallet_history(parsed.query)
            return
        if parsed.path == "/api/wallet/trend":
            self._handle_wallet_trend(parsed.query)
            return
        if parsed.path == "/api/alerts":
            self._handle_alerts(parsed.query)
            return
        if parsed.path == "/api/events":
            self._send_json({"events": EVENTS.recent()})
            return
        if parsed.path == "/api/assessment/commit/verify":
            self._handle_commit_verify(parsed.query)
            return
        if parsed.path == "/" and REACT_DIST_DIR.exists():
            self._send_static(REACT_DIST_DIR / "index.html")
            return
        if parsed.path in {"/", "/frontend/api-workspace.html"}:
            self._send_static(FRONTEND_DIR / "api-workspace.html")
            return
        if parsed.path == "/frontend/mock-workspace.html":
            self._send_static(FRONTEND_DIR / "mock-workspace.html")
            return
        if not parsed.path.startswith("/api/") and parsed.path != "/mcp" and REACT_DIST_DIR.exists():
            self._send_react_asset_or_index(parsed.path)
            return
        self._send_json({"error": "not_found", "path": parsed.path}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/wallet/scan":
            self._handle_scan(parsed.query)
            return
        if parsed.path == "/api/agent/explain":
            self._handle_explain()
            return
        if parsed.path == "/api/risk/evaluate-wallet":
            self._handle_risk_evaluate(parsed.query)
            return
        if parsed.path == "/api/simulation/approval":
            self._handle_simulation("approval_revoke_impact")
            return
        if parsed.path == "/api/simulation/portfolio":
            self._handle_simulation("portfolio_adjustment")
            return
        if parsed.path == "/api/assessment/commit":
            self._handle_commit()
            return
        if parsed.path == "/api/assessment/commit/calldata":
            self._handle_commit_calldata()
            return
        if parsed.path == "/api/assessment/outcome":
            self._handle_outcome()
            return
        if parsed.path == "/api/policy/commit-check":
            self._handle_commit_check()
            return
        if parsed.path == "/api/alerts/resolve":
            self._handle_alert_resolve()
            return
        if parsed.path.startswith("/api/alerts/") and parsed.path.endswith("/resolve"):
            alert_id = parsed.path.removeprefix("/api/alerts/").removesuffix("/resolve").strip("/")
            self._handle_alert_resolve(alert_id=alert_id)
            return
        if parsed.path == "/api/enhancements":
            self._handle_enhancement("summary")
            return
        if parsed.path == "/api/nft/approvals":
            self._handle_enhancement("nft")
            return
        if parsed.path == "/api/revoke/prepare":
            self._handle_enhancement("revoke")
            return
        if parsed.path == "/api/defi/positions":
            self._handle_enhancement("defi")
            return
        if parsed.path == "/api/security/goplus-full":
            self._handle_enhancement("goplus")
            return
        if parsed.path == "/api/simulation/transaction":
            self._handle_enhancement("tx_simulation")
            return
        if parsed.path == "/api/social/share-card":
            self._handle_enhancement("share")
            return
        if parsed.path == "/api/reputation/feedback":
            self._handle_enhancement("reputation")
            return
        if parsed.path == "/mcp":
            self._handle_mcp()
            return
        self._send_json({"error": "not_found", "path": parsed.path}, HTTPStatus.NOT_FOUND)

    def _handle_scan(self, query: str) -> None:
        body = self._read_json()
        response = self._scan_response_from_request(
            query=query,
            body=body,
            include_explanation_default=True,
            record_memory=True,
        )
        if response is not None:
            self._send_json(response)

    def _scan_response_from_request(
        self,
        *,
        query: str,
        body: dict[str, Any],
        include_explanation_default: bool,
        record_memory: bool,
    ) -> dict[str, Any] | None:
        params = parse_qs(query)
        fixture_id = (
            body.get("fixtureId")
            or (params.get("fixtureId") or ["high_risk_wallet"])[0]
            or "high_risk_wallet"
        )
        data_mode = (
            body.get("dataMode")
            or (params.get("dataMode") or ["demo"])[0]
            or "demo"
        )
        wallet_address = body.get("walletAddress") or (params.get("walletAddress") or [None])[0]
        benchmark_case_id = body.get("benchmarkCaseId") or (params.get("benchmarkCaseId") or [None])[0]
        benchmark_case_label = body.get("benchmarkCaseLabel") or (params.get("benchmarkCaseLabel") or [None])[0]
        target_id = body.get("targetId") or body.get("scanTargetId") or (params.get("targetId") or [None])[0]
        requested_chain_id = _optional_body_int(body, "chainId") or _optional_query_int(params, "chain_id") or _optional_query_int(params, "chainId")
        include_explanation = _bool_request_value(
            body.get("includeExplanation"),
            default=include_explanation_default,
        )
        try:
            history_options = _history_options_from_request(body, params)
        except ValueError as exc:
            self._send_json(
                {"error": "bad_request", "message": str(exc)},
                HTTPStatus.BAD_REQUEST,
            )
            return None
        if data_mode not in {"demo", "replay", "live"}:
            self._send_json(
                {"error": "bad_request", "message": "dataMode must be demo, replay, or live"},
                HTTPStatus.BAD_REQUEST,
            )
            return None
        if data_mode == "live" and not wallet_address:
            self._send_json(
                {"error": "bad_request", "message": "walletAddress is required for live dataMode"},
                HTTPStatus.BAD_REQUEST,
            )
            return None
        adapter = None
        if data_mode == "live":
            try:
                config = MantleLensConfig.from_env()
                if target_id or requested_chain_id is not None:
                    target = resolve_chain_target(config, target_id=target_id if isinstance(target_id, str) else None, chain_id=requested_chain_id)
                    adapter = LiveWalletAdapter(config=config_for_chain_target(config, target), chain_target=target)
                else:
                    adapter = LiveWalletAdapter.from_env()
            except ChainTargetError as exc:
                self._send_json(
                    {"error": "bad_request", "message": str(exc)},
                    HTTPStatus.BAD_REQUEST,
                )
                return None
        runner = WalletGuardRunner(
            adapter=adapter,
            trend_store=TREND_STORE if record_memory else InMemoryTrendStore(),
            alert_store=ALERT_STORE if record_memory else InMemoryAlertStore(),
            history_store=ASSESSMENT_HISTORY_STORE if record_memory else InMemoryAssessmentHistoryStore(),
        )
        try:
            response = runner.scan_wallet(
                fixture_id=fixture_id,
                wallet_address=wallet_address if isinstance(wallet_address, str) else None,
                history_options=history_options,
                include_explanation=include_explanation,
                benchmark_case={
                    "id": benchmark_case_id,
                    "label": benchmark_case_label,
                }
                if benchmark_case_id or benchmark_case_label
                else None,
            )
        except FixtureNotFoundError as exc:
            self._send_json({"error": "fixture_not_found", "message": str(exc)}, HTTPStatus.BAD_REQUEST)
            return None
        except WorkflowError as exc:
            self._send_json({"error": "workflow_error", "message": str(exc)}, HTTPStatus.CONFLICT)
            return None
        return response

    def _handle_wallet_projection(self, query: str, projection: str) -> None:
        scan = self._scan_response_from_request(
            query=query,
            body={},
            include_explanation_default=False,
            record_memory=False,
        )
        if scan is None:
            return
        self._send_json(_wallet_projection_payload(scan, projection))

    def _handle_risk_evaluate(self, query: str) -> None:
        body = self._read_json()
        scan = self._scan_response_from_request(
            query=query,
            body=body,
            include_explanation_default=False,
            record_memory=False,
        )
        if scan is None:
            return
        self._send_json(
            {
                "assessment": scan["assessment"],
                "evidenceBundle": scan["evidenceBundle"],
                "coverage": scan["coverage"],
                "trace": scan["trace"],
                "dataMode": scan["assessment"]["dataMode"],
                "limitations": _projection_limitations(scan),
            }
        )

    def _handle_explain(self) -> None:
        body = self._read_json()
        assessment = body.get("assessment")
        evidence = body.get("evidence")
        if not isinstance(assessment, dict) or not isinstance(evidence, list):
            self._send_json(
                {"error": "bad_request", "message": "assessment and evidence are required"},
                HTTPStatus.BAD_REQUEST,
            )
            return
        candidate = body.get("candidate")
        if isinstance(candidate, dict):
            self._send_json(guarded_explanation(candidate, assessment, evidence))
            return
        self._send_json(
            rule_based_explanation(
                assessment,
                evidence,
                fallback_reason="HTTP rule fallback",
            )
        )

    def _handle_simulation(self, simulation_type: str) -> None:
        body = self._read_json()
        assessment = body.get("assessment")
        if not isinstance(assessment, dict):
            self._send_json(
                {"error": "bad_request", "message": "assessment is required"},
                HTTPStatus.BAD_REQUEST,
            )
            return
        runner = WalletGuardRunner()
        try:
            response = runner.simulate(
                assessment,
                simulation_type=simulation_type,
                action_id=body.get("actionId"),
            )
        except WorkflowError as exc:
            self._send_json({"error": "workflow_error", "message": str(exc)}, HTTPStatus.CONFLICT)
            return
        self._send_json(response)

    def _handle_commit(self) -> None:
        body = self._read_json()
        assessment = body.get("assessment")
        if not isinstance(assessment, dict):
            self._send_json(
                {"error": "bad_request", "message": "assessment is required"},
                HTTPStatus.BAD_REQUEST,
            )
            return
        idempotency_key = body.get("idempotencyKey")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            self._send_json(
                {"error": "bad_request", "message": "idempotencyKey is required"},
                HTTPStatus.BAD_REQUEST,
            )
            return
        if body.get("confirmationReceived") is not True:
            self._send_json(
                {"error": "bad_request", "message": "confirmationReceived must be true"},
                HTTPStatus.BAD_REQUEST,
            )
            return
        record_mode = body.get("recordMode") or "local_only"
        if record_mode not in {"local_only", "onchain"}:
            self._send_json(
                {"error": "bad_request", "message": "recordMode must be local_only or onchain"},
                HTTPStatus.BAD_REQUEST,
            )
            return
        if record_mode == "onchain" and assessment.get("dataMode") != "live":
            self._send_json(
                {"error": "bad_request", "message": "recordMode=onchain requires a live assessment"},
                HTTPStatus.BAD_REQUEST,
            )
            return
        recorder = AssessmentRecorder.from_env() if record_mode == "onchain" else LocalOnlyAssessmentRecorder()
        ledger = InMemoryLedger(
            records=LEDGER.records,
            idempotency=LEDGER.idempotency,
            lock=LEDGER.lock,
            recorder=recorder,
        )
        runner = WalletGuardRunner(ledger=ledger)
        try:
            response = runner.commit_assessment(
                assessment,
                idempotency_key=idempotency_key.strip(),
                confirmation_received=True,
                simulation=body.get("simulation") if isinstance(body.get("simulation"), dict) else None,
            )
        except WorkflowError as exc:
            self._send_json({"error": "workflow_error", "message": str(exc)}, HTTPStatus.CONFLICT)
            return
        response["record"]["requestedRecordMode"] = record_mode
        self._send_json(response, HTTPStatus.ACCEPTED)

    def _handle_commit_calldata(self) -> None:
        body = self._read_json()
        assessment = body.get("assessment")
        if not isinstance(assessment, dict):
            self._send_json(
                {"error": "bad_request", "message": "assessment is required"},
                HTTPStatus.BAD_REQUEST,
            )
            return
        if assessment.get("dataMode") != "live":
            self._send_json(
                {"error": "bad_request", "message": "wallet-confirmed on-chain proof calldata requires a live assessment"},
                HTTPStatus.BAD_REQUEST,
            )
            return
        try:
            payload = build_assessment_commit_calldata(
                assessment,
                assessment_uri=body.get("assessmentUri") if isinstance(body.get("assessmentUri"), str) else None,
            )
        except Exception as exc:
            self._send_json(
                {
                    "error": "commit_calldata_unavailable",
                    "message": str(exc),
                    "onchainWriteAttempted": False,
                    "privateKeyRequired": False,
                    "walletConfirmationRequired": True,
                },
                HTTPStatus.CONFLICT,
            )
            return
        self._send_json(payload)

    def _handle_outcome(self) -> None:
        body = self._read_json()
        assessment_id = body.get("assessmentId")
        outcome_hash = body.get("outcomeHash")
        user_response = body.get("userResponse")
        idempotency_key = body.get("idempotencyKey")
        if not all(isinstance(value, str) and value for value in [assessment_id, outcome_hash, user_response, idempotency_key]):
            self._send_json(
                {
                    "error": "bad_request",
                    "message": "assessmentId, outcomeHash, userResponse, and idempotencyKey are required",
                },
                HTTPStatus.BAD_REQUEST,
            )
            return
        record = LEDGER.record_outcome(
            assessment_id=assessment_id,
            outcome_hash=outcome_hash,
            user_response=user_response,
            idempotency_key=idempotency_key,
            trace_id=body.get("traceId") if isinstance(body.get("traceId"), str) else f"trace_outcome_{assessment_id}",
        )
        EVENTS.record(
            "assessment_outcome_recorded",
            run_id=f"run_outcome_{assessment_id}",
            trace_id=record["traceId"],
            wallet_hash=record.get("walletHash") or "unknown",
            assessment_id=assessment_id,
            state="OUTCOME_RECORDED",
            data_mode=record.get("dataMode"),
            properties={
                "outcomeHash": outcome_hash,
                "outcomeStatus": record["outcomeStatus"],
                "realExecutionAllowed": record["realExecutionAllowed"],
            },
        )
        self._send_json({"record": record}, HTTPStatus.ACCEPTED)

    def _handle_benchmark(self, query: str) -> None:
        params = parse_qs(query)
        wallet_hash = (params.get("walletHash") or [None])[0]
        limit_raw = (params.get("limit") or ["20"])[0]
        try:
            limit = max(1, min(100, int(limit_raw)))
        except ValueError:
            limit = 20
        records = LEDGER.history(wallet_hash=wallet_hash, limit=limit)
        EVENTS.record(
            "benchmark_history_viewed",
            run_id=f"run_benchmark_{len(records)}",
            trace_id=f"trace_benchmark_{len(records)}",
            wallet_hash=wallet_hash or "all",
            state="BENCHMARK_UPDATED",
            properties={"recordCount": len(records)},
        )
        self._send_json({"records": records})

    def _handle_wallet_history(self, query: str) -> None:
        params = parse_qs(query)
        wallet_hash = (params.get("walletHash") or params.get("wallet_hash") or [None])[0]
        address = (params.get("address") or params.get("walletAddress") or [None])[0]
        chain_id = _optional_query_int(params, "chain_id") or _optional_query_int(params, "chainId")
        raw_mode = (params.get("mode") or [None])[0]
        mode = None if raw_mode == "all" else raw_mode
        if not wallet_hash and not address:
            self._send_json(
                {"error": "bad_request", "message": "address or walletHash is required"},
                HTTPStatus.BAD_REQUEST,
            )
            return
        limit = _query_int(params, "limit", default=20, minimum=1, maximum=100)
        selected_mode, records = _history_records_for_request(
            address=address,
            wallet_hash=wallet_hash,
            chain_id=chain_id,
            mode=mode,
            allow_all=raw_mode == "all",
            limit=limit,
        )
        history_payload = build_history_response(
            records,
            requested_address=address,
            requested_wallet_hash=wallet_hash,
            chain_id=chain_id,
            mode=selected_mode,
        )
        trend = ASSESSMENT_HISTORY_STORE.trend(
            address=address,
            wallet_hash=wallet_hash,
            chain_id=chain_id,
            mode=selected_mode,
            limit=limit,
        )
        if wallet_hash and not address and not raw_mode and trend.get("status") == "comparable":
            trend = {**trend, "trendStatus": trend.get("trendStatus"), "status": "available"}
        resolved_wallet_hash = history_payload.get("walletHash") or wallet_hash
        alerts = ALERT_STORE.list_alerts(
            wallet_hash=resolved_wallet_hash,
            wallet_address=address,
            chain_id=chain_id,
            mode=selected_mode,
            status="all",
            limit=limit,
        )
        benchmark_records = LEDGER.history(wallet_hash=resolved_wallet_hash, limit=limit) if resolved_wallet_hash else []
        self._send_json(
            {
                **history_payload,
                "modeSelection": "explicit_all" if raw_mode == "all" else "explicit" if raw_mode else "latest_mode_without_mixing",
                "trend": trend,
                "benchmarkRecords": benchmark_records,
                "alerts": alerts,
            }
        )

    def _handle_wallet_trend(self, query: str) -> None:
        params = parse_qs(query)
        wallet_hash = (params.get("walletHash") or params.get("wallet_hash") or [None])[0]
        address = (params.get("address") or params.get("walletAddress") or [None])[0]
        chain_id = _optional_query_int(params, "chain_id") or _optional_query_int(params, "chainId")
        raw_mode = (params.get("mode") or [None])[0]
        mode = None if raw_mode == "all" else raw_mode
        if not wallet_hash and not address:
            self._send_json(
                {"error": "bad_request", "message": "address or walletHash is required"},
                HTTPStatus.BAD_REQUEST,
            )
            return
        limit = _query_int(params, "limit", default=20, minimum=1, maximum=100)
        selected_mode, _ = _history_records_for_request(
            address=address,
            wallet_hash=wallet_hash,
            chain_id=chain_id,
            mode=mode,
            allow_all=raw_mode == "all",
            limit=limit,
        )
        self._send_json(
            ASSESSMENT_HISTORY_STORE.trend(
                address=address,
                wallet_hash=wallet_hash,
                chain_id=chain_id,
                mode=selected_mode,
                limit=limit,
            )
        )

    def _handle_alerts(self, query: str) -> None:
        params = parse_qs(query)
        wallet_hash = (params.get("walletHash") or params.get("wallet_hash") or [None])[0]
        address = (params.get("address") or params.get("walletAddress") or [None])[0]
        chain_id = _optional_query_int(params, "chain_id") or _optional_query_int(params, "chainId")
        mode = (params.get("mode") or [None])[0]
        if mode == "all":
            mode = None
        status = (params.get("status") or ["open"])[0]
        if status not in {"open", "resolved", "all"}:
            self._send_json(
                {"error": "bad_request", "message": "status must be open, resolved, or all"},
                HTTPStatus.BAD_REQUEST,
            )
            return
        limit = _query_int(params, "limit", default=50, minimum=1, maximum=100)
        alerts = ALERT_STORE.list_alerts(
            wallet_hash=wallet_hash,
            wallet_address=address,
            chain_id=chain_id,
            mode=mode,
            status=status,
            limit=limit,
        )
        self._send_json(
            {
                "schemaVersion": "mantlelens.alerts.v1",
                "alerts": alerts,
                "status": status,
                "walletHash": wallet_hash,
                "walletAddress": address,
                "chainId": chain_id,
                "mode": mode,
            }
        )

    def _handle_alert_resolve(self, alert_id: str | None = None) -> None:
        body = self._read_json()
        alert_id = alert_id or body.get("alertId") or body.get("alert_id")
        if not isinstance(alert_id, str) or not alert_id:
            self._send_json(
                {"error": "bad_request", "message": "alertId is required"},
                HTTPStatus.BAD_REQUEST,
            )
            return
        resolved = ALERT_STORE.resolve(
            alert_id=alert_id,
            resolution_note=body.get("resolutionNote") if isinstance(body.get("resolutionNote"), str) else None,
        )
        if resolved is None:
            self._send_json(
                {"error": "not_found", "message": "alert not found"},
                HTTPStatus.NOT_FOUND,
            )
            return
        self._send_json({"alert": resolved})

    def _handle_commit_verify(self, query: str) -> None:
        params = parse_qs(query)
        tx_hash = (params.get("tx_hash") or params.get("txHash") or [None])[0]
        if not tx_hash:
            self._send_json(
                {"error": "bad_request", "message": "tx_hash is required"},
                HTTPStatus.BAD_REQUEST,
            )
            return
        assessment_id = (params.get("assessment_id") or params.get("assessmentId") or [None])[0]
        expected_assessment_hash = (params.get("assessment_hash") or params.get("assessmentHash") or [None])[0]
        local_record = _find_assessment_record(
            assessment_id=assessment_id,
            tx_hash=tx_hash,
        )
        if not expected_assessment_hash and local_record:
            expected_assessment_hash = local_record.get("assessmentHash")

        verification = AssessmentReadbackVerifier.from_env().verify_tx(
            tx_hash,
            expected_assessment_hash=expected_assessment_hash if isinstance(expected_assessment_hash, str) else None,
        )
        verification["localAssessmentId"] = local_record.get("assessmentId") if local_record else assessment_id
        verification["localAssessmentHash"] = local_record.get("assessmentHash") if local_record else expected_assessment_hash
        linked_record = ASSESSMENT_HISTORY_STORE.attach_commit_verification(verification)
        if linked_record:
            verification["linkedHistoryRecordId"] = linked_record.get("historyRecordId")
        self._send_json(verification)

    def _handle_commit_check(self) -> None:
        body = self._read_json()
        runner = WalletGuardRunner(policy=PolicyEngine(), trace=TraceRecorder())
        response = runner.simulate_commit_policy_check(
            assessment_hash=body.get("assessmentHash", ""),
            confirmation_received=bool(body.get("confirmationReceived", False)),
            idempotency_key=body.get("idempotencyKey"),
        )
        status = HTTPStatus.OK if response["allowed"] else HTTPStatus.CONFLICT
        self._send_json(response, status)

    def _handle_enhancement(self, module: str) -> None:
        body = self._read_json()
        handlers = {
            "summary": enhancement_summary,
            "nft": detect_nft_approvals,
            "revoke": prepare_manual_revoke,
            "defi": parse_defi_positions,
            "goplus": evaluate_goplus_full_security,
            "tx_simulation": simulate_transaction,
            "share": build_social_share_card,
            "reputation": record_reputation_feedback,
        }
        handler = handlers[module]
        self._send_json(handler(body), HTTPStatus.ACCEPTED if module == "reputation" else HTTPStatus.OK)

    def _handle_mcp(self) -> None:
        body = self._read_json()
        method = body.get("method")
        request_id = body.get("id")
        try:
            if method in {"tools/list", "list_tools"}:
                self._send_json(mcp_list_response(request_id))
                return
            if method in {"tools/call", "call_tool"}:
                params = body.get("params") or {}
                name = params.get("name")
                arguments = params.get("arguments") or {}
                if not isinstance(name, str):
                    self._send_json(
                        {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "params.name is required"}},
                        HTTPStatus.BAD_REQUEST,
                    )
                    return
                self._send_json(mcp_call_response(name, arguments, request_id=request_id))
                return
            self._send_json(
                {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Unknown MCP method: {method}"}},
                HTTPStatus.BAD_REQUEST,
            )
        except Exception as exc:
            self._send_json(
                {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": str(exc)}},
                HTTPStatus.BAD_REQUEST,
            )

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self._cors_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_empty(self, status: HTTPStatus) -> None:
        self.send_response(status)
        self._cors_headers()
        self.end_headers()

    def _send_static(self, path: Path) -> None:
        if not path.exists():
            self._send_json({"error": "not_found", "path": str(path)}, HTTPStatus.NOT_FOUND)
            return
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self._cors_headers()
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_react_asset_or_index(self, request_path: str) -> None:
        requested = request_path.lstrip("/")
        candidate = (REACT_DIST_DIR / requested).resolve()
        dist_root = REACT_DIST_DIR.resolve()
        if candidate.is_file() and (candidate == dist_root or dist_root in candidate.parents):
            self._send_static(candidate)
            return
        self._send_static(REACT_DIST_DIR / "index.html")

    def _cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _base_url(self) -> str:
        host = self.headers.get("Host") or "127.0.0.1:8765"
        proto = self.headers.get("X-Forwarded-Proto") or ("http" if host.startswith(("127.0.0.1", "localhost")) else "https")
        return f"{proto}://{host}"


def create_server(host: str = "127.0.0.1", port: int = 8765, *, quiet: bool = False) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), MantleLensRequestHandler)
    server.quiet = quiet  # type: ignore[attr-defined]
    return server


def _find_assessment_record(
    *,
    assessment_id: str | None = None,
    tx_hash: str | None = None,
) -> dict[str, Any] | None:
    normalized_tx_hash = str(tx_hash or "").strip().lower()
    with LEDGER.lock:
        records = [dict(record) for record in LEDGER.records.values()]
    for record in records:
        if assessment_id and record.get("assessmentId") == assessment_id:
            return record
        if normalized_tx_hash and str(record.get("assessmentTx") or "").lower() == normalized_tx_hash:
            return record
    return None


def _history_options_from_body(body: dict[str, Any]) -> HistoryPageOptions | None:
    raw = body.get("historyOptions")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("historyOptions must be an object")
    page_size = _optional_int(raw, "pageSize", default=100)
    max_pages = _optional_int(raw, "maxPages", default=3)
    from_block = _optional_int(raw, "fromBlock", default=0)
    to_block = raw.get("toBlock", "latest")
    if isinstance(to_block, str):
        to_block_value: str | int = to_block
    elif isinstance(to_block, int):
        to_block_value = to_block
    else:
        raise ValueError("historyOptions.toBlock must be an integer or latest")
    sort = raw.get("sort", "desc")
    if not isinstance(sort, str):
        raise ValueError("historyOptions.sort must be asc or desc")
    try:
        return HistoryPageOptions(
            page_size=page_size,
            max_pages=max_pages,
            from_block=from_block,
            to_block=to_block_value,
            sort=sort,
        )
    except ValueError as exc:
        raise ValueError(f"Invalid historyOptions: {exc}") from exc


def _history_options_from_request(
    body: dict[str, Any],
    params: dict[str, list[str]],
) -> HistoryPageOptions | None:
    if "historyOptions" in body:
        return _history_options_from_body(body)
    query_keys = {"pageSize", "maxPages", "fromBlock", "toBlock", "sort"}
    if not any(key in params for key in query_keys):
        return None
    raw = {}
    for key in query_keys:
        if key in params:
            raw[key] = params[key][0]
    return _history_options_from_body({"historyOptions": raw})


def _optional_int(raw: dict[str, Any], key: str, *, default: int) -> int:
    value = raw.get(key, default)
    if isinstance(value, bool):
        raise ValueError(f"historyOptions.{key} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"historyOptions.{key} must be an integer") from exc


def _query_int(
    params: dict[str, list[str]],
    key: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = (params.get(key) or [str(default)])[0]
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


def _optional_query_int(params: dict[str, list[str]], key: str) -> int | None:
    if key not in params:
        return None
    raw = params[key][0]
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _optional_body_int(body: dict[str, Any], key: str) -> int | None:
    if key not in body or body.get(key) is None:
        return None
    try:
        return int(body[key])
    except (TypeError, ValueError):
        return None


def _history_records_for_request(
    *,
    address: str | None,
    wallet_hash: str | None,
    chain_id: int | None,
    mode: str | None,
    allow_all: bool,
    limit: int,
) -> tuple[str | None, list[dict[str, Any]]]:
    if mode or allow_all:
        return mode, ASSESSMENT_HISTORY_STORE.list_records(
            address=address,
            wallet_hash=wallet_hash,
            chain_id=chain_id,
            mode=mode,
            limit=limit,
        )
    records = ASSESSMENT_HISTORY_STORE.list_records(
        address=address,
        wallet_hash=wallet_hash,
        chain_id=chain_id,
        mode=None,
        limit=limit,
    )
    if not records:
        return None, []
    latest_mode = records[0].get("mode")
    if not latest_mode:
        return None, records
    return str(latest_mode), [
        record
        for record in records
        if record.get("mode") == latest_mode
    ][:limit]


def _bool_request_value(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _wallet_projection_payload(scan: dict[str, Any], projection: str) -> dict[str, Any]:
    assessment = scan["assessment"]
    coverage = scan["coverage"]
    tool_outputs = scan.get("toolOutputs", {})
    base = {
        "wallet": assessment["wallet"],
        "chainId": assessment["chainId"],
        "dataMode": assessment["dataMode"],
        "dataStatus": assessment["dataStatus"],
        "dataConfidence": assessment["dataConfidence"],
        "coverage": coverage,
        "evidenceBundleHash": scan["evidenceBundle"]["evidenceBundleHash"],
        "limitations": _projection_limitations(scan),
    }

    if projection == "balances":
        rows = _balance_rows(scan)
        return {
            **base,
            "nativeBalance": (tool_outputs.get("getNativeBalance", {}).get("output") or {}).get("balance"),
            "balances": rows,
            "inventory": scan.get("inventory"),
            "sourceStatus": (tool_outputs.get("getKnownTokenBalances", {}) or {}).get("sourceStatus"),
            "dataCoverage": (tool_outputs.get("getKnownTokenBalances", {}) or {}).get("dataCoverage"),
        }

    if projection == "approvals":
        output = (tool_outputs.get("getTokenApprovals", {}).get("output") or {})
        return {
            **base,
            "mode": "indexed_api" if assessment["dataMode"] == "live" else "rpc_fallback",
            "approvals": output.get("approvals", []),
            "pageInfo": output.get("pageInfo"),
            "sourceStatus": (tool_outputs.get("getTokenApprovals", {}) or {}).get("sourceStatus"),
            "dataCoverage": (tool_outputs.get("getTokenApprovals", {}) or {}).get("dataCoverage"),
            "allowanceConfirmationRequired": True,
        }

    if projection == "transfers":
        output = (tool_outputs.get("getTransferLogs", {}).get("output") or {})
        return {
            **base,
            "transfers": output.get("transfers", []),
            "pageInfo": output.get("pageInfo"),
            "sourceStatus": (tool_outputs.get("getTransferLogs", {}) or {}).get("sourceStatus"),
            "dataCoverage": (tool_outputs.get("getTransferLogs", {}) or {}).get("dataCoverage"),
        }

    if projection == "exposure":
        output = (tool_outputs.get("getRwaYieldExposure", {}).get("output") or {})
        return {
            **base,
            "portfolioExposure": _portfolio_exposure(_balance_rows(scan)),
            "rwaYieldExposure": output.get("rwaYieldExposure", {}),
            "subScores": assessment["subScores"],
            "topRisks": [
                risk
                for risk in assessment["topRisks"]
                if risk.get("type") in {"concentration", "rwa_yield", "defi"}
            ],
            "sourceStatus": (tool_outputs.get("getRwaYieldExposure", {}) or {}).get("sourceStatus"),
            "dataCoverage": (tool_outputs.get("getRwaYieldExposure", {}) or {}).get("dataCoverage"),
        }

    if projection == "data_availability":
        return {
            **base,
            "dataCompleteness": coverage["dataCompleteness"],
            "sourceAvailability": coverage["sourceAvailability"],
            "pageCoverage": coverage.get("pageCoverage", {}),
            "missingDataIsSafe": False,
        }

    return {**base, "error": "unknown_projection", "projection": projection}


def _balance_rows(scan: dict[str, Any]) -> list[dict[str, Any]]:
    tool_outputs = scan.get("toolOutputs", {})
    rows: list[dict[str, Any]] = []
    native = (tool_outputs.get("getNativeBalance", {}).get("output") or {}).get("balance")
    if isinstance(native, dict):
        rows.append(native)
    known_rows = (tool_outputs.get("getKnownTokenBalances", {}).get("output") or {}).get("balances", [])
    if isinstance(known_rows, list):
        rows.extend(item for item in known_rows if isinstance(item, dict))
    return rows


def _portfolio_exposure(balances: list[dict[str, Any]]) -> dict[str, Any]:
    valued = [item for item in balances if float(item.get("valueUsd") or 0) > 0]
    total_value = round(sum(float(item.get("valueUsd") or 0) for item in valued), 2)
    ranked = sorted(valued, key=lambda item: float(item.get("valueUsd") or 0), reverse=True)
    top_asset = ranked[0] if ranked else None
    top_asset_pct = round(float(top_asset.get("valueUsd") or 0) / total_value * 100, 2) if top_asset and total_value else 0
    top3_pct = round(sum(float(item.get("valueUsd") or 0) for item in ranked[:3]) / total_value * 100, 2) if total_value else 0
    return {
        "totalWalletValueUsd": total_value,
        "topAsset": top_asset,
        "topAssetPct": top_asset_pct,
        "top3AssetsPct": top3_pct,
        "tokenCount": len(balances),
        "pricedTokenCount": len(valued),
        "calculationMode": "known_token_or_provider_balances",
    }


def _projection_limitations(scan: dict[str, Any]) -> list[str]:
    limitations: list[str] = []
    for result in scan.get("toolOutputs", {}).values():
        limitation = result.get("limitation") if isinstance(result, dict) else None
        if limitation:
            limitations.append(str(limitation))
    for source in scan.get("coverage", {}).get("sourceAvailability", {}).values():
        if isinstance(source, dict) and source.get("limitation"):
            limitations.append(str(source["limitation"]))
    return list(dict.fromkeys(limitations))


def main() -> None:
    parser = argparse.ArgumentParser(description="MantleLens Wallet Guard local demo server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    server = create_server(args.host, args.port, quiet=args.quiet)
    print(f"MantleLens demo server listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
