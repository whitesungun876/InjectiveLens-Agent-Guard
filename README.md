# InjectiveLens Agent Guard

A safety and proof layer before AI agents execute trades on Injective.

InjectiveLens Agent Guard is the Injective Nova version of the MantleLens architecture. It turns the original evidence-bound wallet risk workflow into an AI trading-agent pre-flight guard:

```text
Natural-language trade request
-> parsed trade intent
-> Injective account / market / position evidence
-> allow / warn / block decision
-> safer trade simulation
-> assessment proof recorded on Injective
-> verified matched proof
```

## Current Status

This folder is a standalone workspace for the Injective version.

- Day 1 product scope, API contract, information architecture, and acceptance checklist are complete.
- Reusable code has been copied from the existing MantleLens codebase as the implementation base.
- Day 2 converted the frontend into an Injective trading pre-flight check experience.
- Day 3 adds a deterministic trade-intent parser and fixture API that serves OpenAPI-shaped pre-flight assessments.
- Day 4 adds a read-only adapter layer. Demo mode uses fixtures; live mode attempts configured Injective endpoints and marks missing data as partial/unknown.
- Day 5 adds an explicit proof boundary: pre-flight checks do not auto-record, proof recording requires confirmation, and verification is read-only.
- Day 6 syncs History and Audit with backend endpoints so proof state stays consistent after record/verify.
- Day 7 persists latest assessment/proof history to a local JSON state file so demo state survives API restart.
- Day 8 restores the latest persisted assessment, proof status, history, and decision audit when the frontend loads.
- Day 9 exposes an agent registration, agent card, and read-only MCP-compatible tool surface for other AI agents.

## Day 1 Artifacts

- [Scope lock](docs/day1/01_scope_lock.md)
- [API contract](docs/day1/02_api_contract.openapi.yaml)
- [Information architecture + wireframe](docs/day1/03_information_architecture_wireframe.md)
- [Acceptance checklist](docs/day1/04_day1_acceptance_checklist.md)

## P0 Demo Goal

The standard demo request is:

```text
Open a 10x long INJ-PERP using 60% of available margin.
```

Expected behavior:

1. Parse the natural-language request into a structured trade intent.
2. Query or replay Injective account, subaccount, market, and position evidence.
3. Detect leverage, margin usage, liquidation distance, and source coverage risks.
4. Block unsafe execution before any order is placed.
5. Simulate a safer alternative, such as `3x long INJ-PERP using 15% of available margin`.
6. Record the assessment hash with an Injective testnet proof transaction.
7. Verify that the on-chain assessment hash matches the local assessment hash.

## Safety Boundaries

P0 does not:

- request private keys
- request seed phrases
- auto-sign
- place real orders by default
- transfer funds
- custody user assets
- claim profit or wallet safety

The product is read-only, simulation-only, and proof-only until an explicitly confirmed future execution path is implemented.

## Folder Structure

```text
backend/         InjectiveLens Day 4 read-only adapter API plus reusable migration base
contracts/       Reusable proof-contract base; P1 may replace with CosmWasm
docs/day1/       InjectiveLens Day 1 PRD, API, IA, acceptance docs
frontend/app/    React app wired to the Day 4 pre-flight API
protocol/        Static protocol snapshots for agent registration, agent card, and MCP tools
scripts/         Reusable QA/dev scripts
tests/           Injective Day 3/Day 4 tests plus copied migration baseline
Dockerfile       Azure Container Apps deployment image
```

## Day 4 API Flow

The backend exposes:

- `POST /api/intent/parse`
- `POST /api/injective/preflight`
- `GET /api/injective/account`
- `GET /api/injective/market`
- `GET /api/injective/positions`
- `GET /api/injective/preflight/latest`
- `POST /api/risk/evaluate-trade`
- `POST /api/simulation/safer-trade`
- `POST /api/proof/verify`
- `GET /api/history/preflight`
- `GET /api/agent/audit`
- `GET /agent-registration.json`
- `GET /.well-known/agent-card.json`
- `GET /mcp/tools`
- `POST /mcp` with `tools/list` and `tools/call`

The standard demo request returns `decision = block`, `riskScore >= 80`, `riskLevel = critical`, simulation-only before/after output, and a verified matched proof record.

Live read-only mode uses environment-configured Injective endpoints when available:

```bash
INJECTIVE_LCD_REST_URL=
INJECTIVE_MARKET_SNAPSHOT_URL=
INJECTIVE_POSITIONS_URL=
INJECTIVE_PROOF_RECORDER_MODE=external_tx
INJECTIVE_PROOF_TX_HASH=
INJECTIVE_PROOF_BLOCK_HEIGHT=
INJECTIVE_PROOF_EXPLORER_URL=
INJECTIVELENS_STATE_FILE=data/injectivelens_state.json
```

If any source is missing or unavailable, the response keeps the same API contract, sets source coverage to partial, and treats missing fields as unknown rather than safe.

Proof states are explicit:

- `ready_to_record`
- `pending`
- `recorded`
- `verified_matched`
- `unavailable`

`POST /api/proof/record` requires `confirmation = user_confirmed_record_assessment`. If `INJECTIVE_PROOF_TX_HASH` is not configured, the proof stays `pending` and the app does not claim an on-chain record. `POST /api/proof/verify` is read-only and only returns `verified_matched` after a recorded Injective testnet proof exists.

The Day 9 MCP surface is intentionally read-only in P0. `preflight_trade_action` can return a full assessment for another agent, but it does not place orders, sign, transfer funds, or mutate chain state. `record_assessment_projection` returns instructions for the REST proof endpoint and still requires explicit confirmation outside MCP.

## Local Development

Install frontend dependencies:

```bash
cd "InjectiveLens Agent Guard/frontend/app"
npm install
```

Run the API:

```bash
cd "InjectiveLens Agent Guard"
./scripts/run_demo.sh
```

Run the frontend:

```bash
cd "InjectiveLens Agent Guard/frontend/app"
npm run dev
```

Then open `http://127.0.0.1:5173/` and run the pre-flight check.

## Azure Deployment

The production deployment path is Azure Container Apps. The Docker image serves the React frontend and Python API from the same origin.

```bash
cd "InjectiveLens Agent Guard"

AZURE_LOCATION=eastus \
AZURE_RESOURCE_GROUP=rg-injectivelens-agent-guard \
AZURE_APP_NAME=injectivelens-agent-guard \
AZURE_ACR_NAME=<globally-unique-acr-name> \
./scripts/azure_deploy_containerapp.sh
```

See [Azure deployment guide](docs/azure_deployment.md) for the full checklist.
