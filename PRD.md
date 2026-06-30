# InjectiveLens Agent Guard PRD

## Vision

InjectiveLens Agent Guard helps AI trading agents avoid unsafe on-chain actions by checking market, margin, position, account, and source coverage risk before execution, then recording a verifiable assessment on Injective.

## Problem

AI agents can now interpret user instructions and interact with financial systems. In trading contexts, that creates a new failure mode: a natural-language request can become a high-risk on-chain action before a human understands the leverage, margin, liquidation, or market data risk.

InjectiveLens solves this by inserting a pre-flight risk layer before AI trading execution.

## Target Users

- AI agent builders using Injective.
- Web3 traders experimenting with prompt-driven trading agents.
- Hackathon evaluators looking for AI x Web3 applications with real Injective integration.

## Core Flow

```text
User prompt
-> trade intent parser
-> Injective read-only data
-> deterministic risk policy
-> evidence-bound decision
-> safer simulation
-> assessment proof record
-> proof verification
```

## P0 Features

1. Natural-language trading request input.
2. Structured `TradeIntent` parser.
3. Demo and live Injective testnet pre-flight modes.
4. Account, market, position, and source coverage evidence.
5. Risk scoring for:
   - leverage risk
   - margin usage risk
   - liquidation distance risk
   - position concentration risk
   - source coverage risk
6. Agent decisions:
   - `allow`
   - `warn`
   - `block`
7. Safer trade simulation.
8. Assessment hash recording on Injective testnet.
9. Read-only proof verification.
10. Evidence, History, and Audit views.

## Non-Goals

- No real trading by default.
- No private key custody.
- No seed phrase handling.
- No auto-signing.
- No fund transfers.
- No guaranteed profit claims.
- No production liquidation engine.

## Demo Acceptance

The standard demo must prove:

```text
Open a 10x long INJ-PERP using 60% of available margin.
```

returns:

```text
Decision: BLOCK
Action: Simulate safer trade
Risk: Critical
Proof: Recorded on Injective testnet
Verification: matched
```

The demo fails if a high-risk request can reach an order-placement path in P0.

## Reference Day 1 Documents

- [Scope lock](docs/day1/01_scope_lock.md)
- [API contract](docs/day1/02_api_contract.openapi.yaml)
- [Information architecture + wireframe](docs/day1/03_information_architecture_wireframe.md)
- [Acceptance checklist](docs/day1/04_day1_acceptance_checklist.md)

