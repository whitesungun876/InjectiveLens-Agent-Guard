# Day 3 Backend API Pre-flight Completion

## Objective

Replace the Day 2 in-memory frontend assessment builder with a deterministic backend fixture API that matches the Day 1 `PreflightAssessment` contract.

## Delivered

- Deterministic `TradeIntent` parser for natural-language trading requests.
- Injective pre-flight fixture API under `backend/injectivelens`.
- OpenAPI-shaped `POST /api/injective/preflight` response.
- Supporting read-only endpoints for account, market, positions, risk, simulation, history, proof verification, and agent audit.
- Frontend `Run agent guard check` now calls the Day 3 API instead of generating assessment data inside `App.tsx`.
- Local demo scripts now start the InjectiveLens API service.

## Standard API Scenario

Request:

```json
{
  "prompt": "Open a 10x long INJ-PERP using 60% of available margin.",
  "address": "inj1wrse2035wdnxrq4gwhnxp0nmeyg6u3vss5uvlp",
  "network": "injective_testnet",
  "mode": "demo_scenario"
}
```

Expected result:

```text
Decision: block
Risk score: 86 / 100
Risk level: critical
Action: Block execution and simulate safer trade
Proof: ready_to_record
Simulation: noBroadcast = true
```

## API Endpoints Implemented

- `GET /api/health`
- `POST /api/intent/parse`
- `POST /api/injective/preflight`
- `GET /api/injective/account`
- `GET /api/injective/market`
- `GET /api/injective/positions`
- `POST /api/risk/evaluate-trade`
- `POST /api/simulation/safer-trade`
- `POST /api/proof/verify`
- `GET /api/history/preflight`
- `GET /api/agent/audit`

## Verification

Backend:

```bash
python3 -m unittest tests.test_injective_day3_api -v
```

Result:

```text
Ran 4 tests
OK
```

Frontend:

```bash
cd frontend/app
npm ci
npm run build
```

Result:

```text
tsc --noEmit && vite build
✓ built
```

Browser smoke:

```json
{
  "loadedTitle": true,
  "day3Status": true,
  "apiHit": true,
  "overviewBlock": true,
  "overviewSignals": true,
  "overviewSimulation": true,
  "overviewProof": true,
  "evidenceBundle": true,
  "evidenceParserSource": true,
  "historyTrend": true,
  "historyProof": true,
  "auditDecision": true,
  "auditTrace": true,
  "noDay2MockCopy": true,
  "noMantleProductCopy": true
}
```

## Files Changed

- `backend/injectivelens/__init__.py`
- `backend/injectivelens/parser.py`
- `backend/injectivelens/fixtures.py`
- `backend/injectivelens/server.py`
- `frontend/app/src/injectivePreflightApi.ts`
- `frontend/app/src/App.tsx`
- `frontend/app/src/styles.css`
- `tests/test_injective_day3_api.py`
- `scripts/run_demo.sh`
- `scripts/run_app.sh`
- `scripts/stop_demo.sh`
- `README.md`

## Day 4 Starting Point

Day 4 should replace the fixture-only account, market, and position sources with real Injective read-only adapters where available, while preserving the same `PreflightAssessment` API contract and the current no-signing safety boundary.
