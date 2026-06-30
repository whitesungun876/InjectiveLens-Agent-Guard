from __future__ import annotations

import argparse
import json
import mimetypes
import os
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .adapters import select_injective_adapter
from .fixtures import (
    DEFAULT_ACCOUNT,
    DEFAULT_NETWORK,
    DEFAULT_SUBACCOUNT_ID,
    build_agent_audit,
    build_preflight_assessment,
    evaluate_trade_risk,
    history_records,
    safer_trade_simulation,
)
from .parser import parse_trade_intent
from .persistence import STATE_STORE
from .proof import hydrate_proof_store, record_assessment_proof, verify_assessment_proof
from .protocol import (
    agent_card,
    agent_registration,
    mcp_call_response,
    mcp_error_response,
    mcp_list_response,
    mcp_tools,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
hydrate_proof_store(STATE_STORE.get_proof_records())
LATEST_ASSESSMENT: dict[str, Any] | None = STATE_STORE.get_latest_assessment()


class InjectiveLensRequestHandler(SimpleHTTPRequestHandler):
    server_version = "InjectiveLensHTTP/0.1"

    def log_message(self, format: str, *args: Any) -> None:
        if getattr(self.server, "quiet", False):
            return
        super().log_message(format, *args)

    def do_OPTIONS(self) -> None:
        self._send_empty(HTTPStatus.NO_CONTENT)

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        if self._serve_static_or_spa(parsed.path, include_body=False):
            return
        self._send_empty(HTTPStatus.NOT_FOUND)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if parsed.path == "/api/health":
            self._send_json(
                {
                    "status": "ok",
                    "service": "injectivelens-agent-guard",
                    "mode": "day9-agent-protocol-api",
                    "day": "9",
                    "stateFile": str(STATE_STORE.path),
                    "hasLatestAssessment": LATEST_ASSESSMENT is not None,
                }
            )
            return
        if parsed.path in {"/agent-registration.json", "/protocol/agent-registration.json"}:
            self._send_json(agent_registration(self._base_url()))
            return
        if parsed.path in {"/.well-known/agent-card.json", "/protocol/agent-card.json"}:
            self._send_json(agent_card(self._base_url()))
            return
        if parsed.path in {"/mcp/tools", "/protocol/mcp-tools-list.json"}:
            self._send_json({"tools": mcp_tools()})
            return
        if parsed.path == "/api/injective/account":
            mode = _query(params, "mode", "demo_scenario")
            adapter = select_injective_adapter(mode)
            self._send_json(
                adapter.account_state(
                    _query(params, "address", DEFAULT_ACCOUNT),
                    _query(params, "subaccountId", DEFAULT_SUBACCOUNT_ID),
                    _query(params, "network", DEFAULT_NETWORK),
                    mode,
                )
            )
            return
        if parsed.path == "/api/injective/market":
            mode = _query(params, "mode", "demo_scenario")
            adapter = select_injective_adapter(mode)
            self._send_json(
                adapter.market_snapshot(
                    _query(params, "market", "INJ-PERP"),
                    _query(params, "network", DEFAULT_NETWORK),
                    mode,
                )
            )
            return
        if parsed.path == "/api/injective/positions":
            mode = _query(params, "mode", "demo_scenario")
            adapter = select_injective_adapter(mode)
            self._send_json(
                adapter.positions(
                    _query(params, "subaccountId", DEFAULT_SUBACCOUNT_ID),
                    _query(params, "network", DEFAULT_NETWORK),
                    mode,
                )
            )
            return
        if parsed.path == "/api/injective/preflight/latest":
            if LATEST_ASSESSMENT is None:
                self._send_json(
                    {
                        "error": "not_found",
                        "message": "No persisted pre-flight assessment is available.",
                    },
                    HTTPStatus.NOT_FOUND,
                )
                return
            self._send_json(LATEST_ASSESSMENT)
            return
        if parsed.path == "/api/history/preflight":
            self._send_json({"records": history_records(LATEST_ASSESSMENT, STATE_STORE.get_assessment_history())})
            return
        if parsed.path == "/api/agent/audit":
            assessment = LATEST_ASSESSMENT or build_preflight_assessment(_default_request())
            self._send_json(build_agent_audit(assessment))
            return
        if self._serve_static_or_spa(parsed.path):
            return
        self._send_json({"error": "not_found", "message": parsed.path}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        global LATEST_ASSESSMENT

        parsed = urlparse(self.path)
        if parsed.path == "/api/intent/parse":
            body = self._read_json()
            self._send_json(parse_trade_intent(str(body.get("prompt") or ""), str(body.get("parserMode") or "deterministic")))
            return
        if parsed.path == "/mcp":
            body = self._read_json()
            method = str(body.get("method") or "")
            request_id = body.get("id")
            if method == "tools/list":
                self._send_json(mcp_list_response(request_id))
                return
            if method == "tools/call":
                params = body.get("params") if isinstance(body.get("params"), dict) else {}
                self._send_json(
                    mcp_call_response(
                        str(params.get("name") or ""),
                        params.get("arguments") if isinstance(params.get("arguments"), dict) else {},
                        request_id=request_id,
                        latest_assessment=LATEST_ASSESSMENT,
                    )
                )
                return
            self._send_json(mcp_error_response(request_id, -32601, f"Unsupported MCP method: {method}"))
            return
        if parsed.path == "/api/injective/preflight":
            body = self._read_json()
            if not str(body.get("prompt") or "").strip():
                self._send_json({"error": "bad_request", "message": "prompt is required", "retryable": False}, HTTPStatus.BAD_REQUEST)
                return
            assessment = build_preflight_assessment(body)
            LATEST_ASSESSMENT = assessment
            STATE_STORE.save_latest_assessment(assessment)
            STATE_STORE.save_assessment_history_record(assessment)
            self._send_json(assessment)
            return
        if parsed.path == "/api/risk/evaluate-trade":
            body = self._read_json()
            self._send_json(
                evaluate_trade_risk(
                    body.get("tradeIntent") or {},
                    body.get("accountState") or {},
                    body.get("marketSnapshot") or {},
                    body.get("positions") or [],
                    str(body.get("mode") or "demo_scenario"),
                )
            )
            return
        if parsed.path == "/api/simulation/safer-trade":
            assessment = LATEST_ASSESSMENT or build_preflight_assessment(_default_request())
            self._send_json(safer_trade_simulation(assessment["parseResult"]["tradeIntent"], assessment["decision"]["riskScore"]))
            return
        if parsed.path == "/api/proof/record":
            body = self._read_json()
            proof, status_code = record_assessment_proof(body, LATEST_ASSESSMENT)
            if LATEST_ASSESSMENT and proof.get("recordedAssessmentHash") == LATEST_ASSESSMENT.get("assessmentHash"):
                LATEST_ASSESSMENT["proof"] = proof
                STATE_STORE.save_latest_assessment(LATEST_ASSESSMENT)
                STATE_STORE.save_assessment_history_record(LATEST_ASSESSMENT)
                STATE_STORE.save_proof_record(proof)
            self._send_json(proof, HTTPStatus(status_code))
            return
        if parsed.path == "/api/proof/verify":
            body = self._read_json()
            verification = verify_assessment_proof(body, LATEST_ASSESSMENT)
            if LATEST_ASSESSMENT and verification.get("status") == "verified_matched":
                LATEST_ASSESSMENT["proof"] = {
                    **LATEST_ASSESSMENT.get("proof", {}),
                    "status": "verified_matched",
                    "txHash": verification.get("txHash"),
                    "explorerUrl": verification.get("explorerUrl"),
                    "recordedAssessmentHash": verification.get("onchainAssessmentHash"),
                    "blockHeight": verification.get("blockHeight"),
                    "message": verification.get("message"),
                }
                STATE_STORE.save_latest_assessment(LATEST_ASSESSMENT)
                STATE_STORE.save_assessment_history_record(LATEST_ASSESSMENT)
                STATE_STORE.save_proof_record({**LATEST_ASSESSMENT["proof"], "assessmentHash": LATEST_ASSESSMENT["assessmentHash"]})
            self._send_json(verification)
            return
        self._send_json({"error": "not_found", "message": parsed.path}, HTTPStatus.NOT_FOUND)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _send_json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(payload)

    def _send_empty(self, status: HTTPStatus) -> None:
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _serve_static_or_spa(self, request_path: str, *, include_body: bool = True) -> bool:
        root = _static_root()
        if root is None:
            return False
        if request_path.startswith("/api/") or request_path == "/mcp":
            return False

        requested = unquote(request_path.split("?", 1)[0]).lstrip("/")
        target = (root / requested).resolve() if requested else root / "index.html"
        try:
            target.relative_to(root)
        except ValueError:
            self._send_json({"error": "bad_request", "message": "Invalid static path"}, HTTPStatus.BAD_REQUEST)
            return True

        if target.is_dir():
            target = target / "index.html"
        if not target.exists() or not target.is_file():
            if "." in Path(requested).name:
                self._send_json({"error": "not_found", "message": request_path}, HTTPStatus.NOT_FOUND)
                return True
            target = root / "index.html"
            if not target.exists():
                return False

        self._send_file(target, include_body=include_body)
        return True

    def _send_file(self, path: Path, *, include_body: bool = True) -> None:
        payload = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        if include_body:
            self.wfile.write(payload)

    def _base_url(self) -> str:
        host = self.headers.get("Host")
        if host:
            return f"http://{host}"
        address, port = self.server.server_address[:2]
        return f"http://{address}:{port}"


def _query(params: dict[str, list[str]], key: str, default: str) -> str:
    values = params.get(key)
    if not values:
        return default
    return values[0] or default


def _default_request() -> dict[str, Any]:
    return {
        "prompt": "Open a 10x long INJ-PERP using 60% of available margin.",
        "address": DEFAULT_ACCOUNT,
        "subaccountId": DEFAULT_SUBACCOUNT_ID,
        "network": DEFAULT_NETWORK,
        "mode": "demo_scenario",
    }


def _static_root() -> Path | None:
    configured = os.getenv("INJECTIVELENS_STATIC_DIR")
    candidates = [
        Path(configured).expanduser() if configured else None,
        PROJECT_ROOT / "frontend" / "app" / "dist",
    ]
    for candidate in candidates:
        if candidate and candidate.exists() and candidate.is_dir():
            return candidate.resolve()
    return None


def reload_state() -> None:
    global LATEST_ASSESSMENT
    LATEST_ASSESSMENT = STATE_STORE.get_latest_assessment()
    hydrate_proof_store(STATE_STORE.get_proof_records())


def run(host: str, port: int, quiet: bool = False) -> None:
    reload_state()
    server = ThreadingHTTPServer((host, port), InjectiveLensRequestHandler)
    server.quiet = quiet  # type: ignore[attr-defined]
    print(f"InjectiveLens API listening on http://{host}:{port}")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run InjectiveLens Day 9 agent protocol API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT") or "8765"))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    run(args.host, args.port, args.quiet)


if __name__ == "__main__":
    main()
