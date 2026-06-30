# InjectiveLens Day 1 Scope Lock

## Project

InjectiveLens Agent Guard is a hackathon MVP for Injective Nova. It is a pre-trade risk intelligence and proof layer for AI trading agents on Injective, not a wallet security dashboard and not an autonomous trading bot.

The project reuses the strongest MantleLens patterns: evidence-bound risk assessment, deterministic policy guardrails, simulation-before-execution, proof verification, history, and decision audit. It changes the domain from "wallet risk before signing" to "AI trading action risk before execution on Injective".

## Product Positioning

**Name:** InjectiveLens Agent Guard

**Tagline:** A safety and proof layer before AI agents execute trades on Injective.

**One-liner:** InjectiveLens checks natural-language trading requests before an AI agent executes them, blocks unsafe actions, simulates safer alternatives, and records a verifiable assessment on Injective.

## Target Hackathon Fit

Injective Nova evaluates innovation, technical implementation, application value, product experience, and ecosystem fit. InjectiveLens is designed around those criteria:

- **Innovation:** AI agent pre-flight risk firewall for on-chain trading actions.
- **Technical implementation:** Natural-language trade intent parsing, Injective read-only account/market/position data, deterministic policy engine, simulation, on-chain assessment proof.
- **Application value:** Helps prevent unsafe AI-agent trading behavior before execution.
- **Product experience:** Human-friendly prompt-to-decision UI with clear allow/warn/block states.
- **Ecosystem fit:** Integrates Injective account/market/position data and records verifiable assessment proof on Injective testnet.

## P0 Goal

Deliver one demoable AI trading risk loop:

`Natural-language trade request -> Parsed trade intent -> Injective account/market/position evidence -> Risk assessment -> Agent decision -> Safer simulation -> Assessment proof -> Verify matched -> History`

P0 must support:

- Demo trading scenarios for high-risk and safer requests.
- Live Injective testnet read-only check for at least one account/subaccount.
- Natural-language trade request input.
- Deterministic trade-intent parser with LLM-ready fallback boundaries.
- Account balance, subaccount balance, market snapshot, open position, and source coverage evidence.
- Risk scoring for leverage, margin usage, liquidation distance, concentration, market data freshness, and source coverage.
- Agent decision states: `allow`, `warn`, `block`.
- Hard block for high-risk or unsupported execution requests.
- Safer simulation for reduced leverage / reduced margin usage / smaller notional.
- Evidence bundle where every risk claim has at least one evidence id.
- Plain-language explanation generated from structured assessment only.
- Assessment hash recording on Injective testnet.
- Read-only proof verification showing local hash, on-chain hash, tx, network, and matched state.
- History that keeps each assessment's proof status independent.
- Decision Audit with allowed actions, blocked actions, LLM boundary, and MCP-style tool trace.

## P0 Non-Goals

P0 explicitly does not include:

- Default real order placement.
- Autonomous perpetual trading.
- Custody of private keys.
- Asking for seed phrases.
- Browser-side private key handling.
- Auto-signing.
- Fund transfers.
- Production liquidation engine.
- Full multi-market portfolio coverage.
- Cross-chain routing.
- Profit prediction.
- Trading advice framed as guaranteed outcome.
- Treating missing Injective data as safe.
- Treating simulated safer trades as executed trades.

## P1 / P2 Parking Lot

P1 candidates:

- Injective MCP Server integration with live tool-call execution.
- `@injective/agent-sdk` agent identity / agent card / registry display.
- CosmWasm AssessmentLogger instead of tx memo proof.
- Azure OpenAI explanation mode.
- Multi-agent trace: Intent Parser Agent, Risk Agent, Proof Agent.
- Injective market selector with multiple perps / spot markets.
- More robust position and liquidation calculations.

P2 candidates:

- AuthZ-based scoped execution preview.
- Real order dry-run if supported by infrastructure.
- Telegram or Discord pre-flight bot.
- Paid risk assessment endpoint.
- Agent reputation feedback.
- Multi-account team dashboard.
- Human-in-the-loop approval workflow for real trading.

## Standard Demo Case

The standard demo request should be:

```text
Open a 10x long INJ-PERP using 60% of available margin.
```

Expected demo behavior:

1. Agent parses the request into a structured trade intent.
2. Injective read-only adapter retrieves account, market, position, and coverage evidence.
3. Risk engine flags high leverage and excessive margin usage.
4. Decision is `BLOCK`.
5. Execution is blocked before any order is placed.
6. Simulation proposes a safer alternative, e.g. `3x long INJ-PERP using 15% of available margin`.
7. Assessment hash is recorded on Injective testnet.
8. Proof verification shows `AssessmentRecorded`, `Verified matched`, network, tx link, local assessment hash, and on-chain assessment hash.
9. History shows the latest assessment as recorded, without applying the same proof to older records.

## Hard Product Rules

- Intent before execution.
- Data before reasoning.
- Evidence before claims.
- Rules before LLM explanation.
- Simulation before any execution path.
- Missing data is unknown, not safe.
- High-risk requests are blocked before execution.
- LLM may explain structured assessment only; it cannot invent evidence, change risk score, or approve blocked actions.
- State-changing tools are disabled by default except explicit assessment proof recording.
- P0 proof records assessment hash only; it does not prove trade profitability or wallet safety.
- No private keys, seed phrases, auto-signing, transfers, swaps, or real order placement in P0 demo mode.

## Required Day 1 Decisions

| Area | Decision | Rationale |
|---|---|---|
| Product name | InjectiveLens Agent Guard | Clear Injective-native repositioning |
| Core user | AI agent builder / Web3 trader reviewing agent actions | Fits AI x Web3 / Injective agent theme |
| Main flow | Natural-language trade request pre-flight | More Injective-native than wallet scan |
| Execution mode | Read-only + simulation + proof | Keeps demo safe and credible |
| Proof strategy P0 | Injective testnet assessment proof; implementation may start with tx memo proof | Fastest path to verifiable chain proof |
| Proof strategy P1 | CosmWasm AssessmentLogger | Stronger long-term proof primitive |
| Agent SDK role | Agent identity / agent card / registry | `@injective/agent-sdk` is identity-oriented |
| MCP role | Trading/account/market tool loop | Injective MCP/Trading Skills fits query/action surface |
| LLM role | Intent parsing assistance and explanation only | Deterministic policy remains authoritative |

## Day 1 Acceptance

- P0/P1/P2 are separated with no ambiguous real-trading scope.
- Demo path is fixed and checkable.
- Product is clearly Injective-native, not a Mantle rename.
- Hard product rules are written as development constraints.
- Proof scope states clearly that assessment proof is not trade safety or profit proof.
- Open assumptions are visible before implementation begins.

## Open Assumptions To Confirm

| Assumption | Current Decision | Impact |
|---|---|---|
| Injective proof mechanism | Start with tx memo proof unless CosmWasm deployment is confirmed | Determines Day 7 workload |
| Injective account for demo | Use a testnet account with faucet funds and stable query results | Determines live demo reliability |
| MCP integration depth | P0 may use SDK/REST for reliability and show MCP-compatible trace; P1 executes MCP tools | Controls integration risk |
| Azure OpenAI | Optional P1; deterministic parser required first | Prevents LLM from blocking P0 |
| Real trading | Disabled in P0 | Keeps security boundary clear |
| Existing MantleLens code | Reuse architecture; do not expose Mantle branding in Injective demo path | Prevents ecosystem-fit penalty |
