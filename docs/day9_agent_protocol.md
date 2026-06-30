# Day 9 Agent Protocol Layer

Day 9 makes InjectiveLens callable by other AI agents instead of only being a standalone UI.

The goal is not to add real trading. The goal is to expose the same pre-flight guard through protocol-shaped surfaces:

```text
agent registration
-> agent card
-> MCP-compatible tools/list
-> MCP-compatible tools/call
-> same evidence-bound pre-flight assessment
```

## What Changed

- Added `backend/injectivelens/protocol.py`.
- Added dynamic HTTP protocol endpoints:
  - `GET /agent-registration.json`
  - `GET /.well-known/agent-card.json`
  - `GET /mcp/tools`
  - `POST /mcp`
- Added static protocol snapshots:
  - `protocol/agent-registration.json`
  - `protocol/agent-card.json`
  - `protocol/mcp-tools-list.json`
- Added an Integration layer panel to Decision Audit.
- Updated health mode to `day9-agent-protocol-api`.

## MCP Tools

The Day 9 MCP-compatible surface exposes:

- `preflight_trade_action`
- `get_injective_account_state`
- `get_market_snapshot`
- `get_open_positions`
- `simulate_safer_trade`
- `get_latest_assessment`
- `record_assessment_projection`

All tools include `readOnlyHint = true`.

`preflight_trade_action` calls the same `build_preflight_assessment` path as the UI and REST API. It returns the decision, evidence, source coverage, simulation, audit trace, and execution boundary.

`record_assessment_projection` is intentionally not a chain mutation. It returns the confirmation and REST endpoint boundary needed for `/api/proof/record`.

## Safety Boundary

Day 9 still does not:

- request private keys
- request seed phrases
- auto-sign
- place orders
- transfer funds
- mutate chain state through MCP
- claim a trade is profitable or safe

The only state-changing proof path remains:

```text
POST /api/proof/record
confirmation = user_confirmed_record_assessment
```

## Acceptance Criteria

- Static protocol JSON files parse successfully and use InjectiveLens branding.
- Agent registration exposes Injective testnet and `realExecutionAllowed = false`.
- Agent card exposes agent skills and security flags.
- `GET /mcp/tools` returns the tool list.
- `POST /mcp` supports `tools/list` and `tools/call`.
- `tools/call -> preflight_trade_action` returns `decision = block` for the standard high-risk request.
- MCP call output proves no order was placed and no auto-signing is allowed.
- Decision Audit shows the Integration layer with registry, agent card, and MCP tool links.
