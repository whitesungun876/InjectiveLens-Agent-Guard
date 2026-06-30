# InjectiveLens Day 1 Information Architecture + Wireframe

## UX Principle

The product must feel like a normal risk pre-flight product, not a benchmark console and not a trading terminal. The user should understand this sequence in under 10 seconds:

`Describe intended agent action -> Run pre-flight -> See allow/warn/block -> Inspect evidence -> Simulate safer action -> Verify proof`

## Top-Level Navigation

| Tab | Purpose | Main Question Answered |
|---|---|---|
| Overview | Run and understand the latest pre-flight check | Should this AI agent execute this trade? |
| Evidence | Inspect the account, market, position, and coverage evidence | Why did the agent decide this? |
| History | Review past pre-flight assessments and proof status | Has this risk changed over time? |
| Audit | Inspect the agent decision loop and integration layer | Is this really an AI agent workflow? |

`Audit` is a secondary action visually separated from Overview / Evidence / History.

## Overview Wireframe

```text
InjectiveLens Agent Guard
A safety and proof layer before AI agents execute trades on Injective

┌──────────────────────────────────────────────────────────────┐
│ PRE-FLIGHT CHECK                                             │
│ Review an AI trading action before execution.                │
│                                                              │
│ Mode                                                         │
│ [Demo trading scenario] [Live Injective testnet check]       │
│                                                              │
│ Natural-language trading request                             │
│ "Open a 10x long INJ-PERP using 60% of available margin."    │
│                                                              │
│ Injective account / subaccount                               │
│ inj1...                                                      │
│                                                              │
│ Scenario summary                                             │
│ Risk: Critical | Action: Block execution | Proof: Available  │
│                                                              │
│ [Run agent guard check]                                      │
│                                                              │
│ Safety note: read-only checks, no auto-sign, no order placed │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────┐ ┌────────────┐
│ BLOCKED: high-risk trading request           │ │ Risk 86/100│
│ 10x leverage + 60% margin usage exceeds safe │ │ Critical   │
│ pre-flight thresholds.                       │ └────────────┘
│                                              │
│ Decision: Block execution                    │
│ Next step: Simulate safer trade              │
└──────────────────────────────────────────────┘

Agent decision
Decision: BLOCK
Evidence bound: 8 items
Allowed: inspect evidence, simulate safer trade, record/verify assessment
Blocked: place order, auto-sign, transfer funds

Core risk signals
[Leverage risk] [Margin usage risk] [Liquidation distance risk] [Source coverage]

Review workflow
[Inspect evidence] [Simulate safer trade] [Record / View proof]

Injective-native signals
Injective testnet · account/subaccount · market data · assessment proof
```

### Overview Acceptance

- The first screen shows "pre-trade risk" rather than "wallet scan".
- Primary CTA is `Run agent guard check`.
- High-risk demo request returns `BLOCK`, not `High` alone.
- Simulation button says `Simulate safer trade`, not revoke/swap.
- Proof button is `Record assessment` or `View Injective proof`.
- No Mantle, Mantlescan, approval anomaly, or wallet guard copy appears in Injective mode.

## Evidence Wireframe

```text
Evidence bundle
8 evidence items supporting 3 risk signals.
Mode: Live Injective testnet
Coverage: Partial / Full
Proof: Recorded on Injective testnet / Not recorded
[View Injective proof]

Risk evidence

Leverage risk
Claim: Requested 10x leverage exceeds safe threshold for this pre-flight profile.
Confidence: 92%
Evidence: 2 items
[Market leverage parameters] [Parsed trade intent]
[View evidence details]

Margin usage risk
Claim: Request uses 60% of available margin.
Confidence: 88%
Evidence: 2 items
[Subaccount balance] [Parsed trade intent]
[View evidence details]

Liquidation distance risk
Claim: Simulated position leaves liquidation distance below threshold.
Confidence: 80%
Evidence: 2 items
[Market mark price] [Simulated liquidation distance]
[View evidence details]

Supporting records
[Account balances] [Open positions] [Market snapshot] [Source coverage]
```

### Evidence Acceptance

- Every risk claim has at least one `evidenceId`.
- Read-only data is not presented as a transaction.
- Source coverage is distinct from proof status.
- Demo replay references cannot look like real Injective tx hashes.
- Technical fields are collapsed by default.

## History Wireframe

```text
Assessment history & risk trend

[Latest score 86/100 Critical]
[Change +12]
[Open review items 3]
[Proof Recorded on Injective testnet]

Risk trend chart

Recent assessments
- Latest assessment
  BLOCK · 86/100 · INJ-PERP · Recorded on Injective testnet
  Top risks: Leverage risk · Margin usage risk · Liquidation distance risk
  [View details] [View Injective proof]

- Previous assessment
  WARN · 44/100 · INJ-PERP · Not recorded
  [View details]

Source coverage
Injective indexer available · Market data available · Position source partial
```

### History Acceptance

- Latest proof status does not overwrite older records.
- `Replay proof only` never appears for live Injective assessments.
- Proof status and record status use separate labels.
- Repeated demo records are grouped.

## Audit Wireframe

```text
Decision Audit
Rules and evidence decide the workflow before LLM explanation.

Decision: BLOCK
Action: Simulate safer trade
Simulation: Available
Reason: High leverage and margin usage exceed thresholds.

Allowed actions
- Inspect evidence
- Simulate safer trade
- Record assessment hash
- Verify assessment

Blocked actions
- Place order
- Auto-sign
- Transfer funds
- LLM-generated transaction execution
- Private-key custody

Agent protocol
MCP-compatible read-only tools · Injective account/market/position adapters
Agent identity: InjectiveLens Agent Guard

MCP-style tool trace
1. ParseTradeIntent
2. GetAccountState
3. GetMarketSnapshot
4. GetOpenPositions
5. EvaluateTradeRisk
6. SimulateSaferTrade
7. RecordAssessment
8. VerifyAssessment

Raw developer trace [collapsed]
```

### Audit Acceptance

- Main Decision Audit matches the current Overview decision.
- Raw internal enum values appear only inside collapsed `Raw developer trace`.
- Agentic loop is visible without reading raw JSON.
- Allowed / blocked actions are explicit.
- LLM boundary is visible.

## Empty / Loading / Error States

### First-Time Empty State

```text
No pre-flight check yet.
Choose a demo scenario or run a live Injective testnet read-only check.
```

### Loading State

```text
Parsing trade intent...
Reading Injective account and market data...
Evaluating risk signals...
Binding evidence...
Preparing proof status...
```

### Low-Confidence State

```text
Partial source coverage.
Missing Injective data is treated as unknown, not safe.
```

### Error State

```text
Pre-flight check could not complete.
No order was placed. Retry with demo data or check source coverage.
```

## Visual Hierarchy Rules

- Product title is largest.
- Risk decision (`ALLOW`, `WARN`, `BLOCK`) is visually stronger than numeric score.
- Red is reserved for blocked/critical states.
- Orange is used for partial/unknown coverage.
- Teal is used for verified proof and safe/available status.
- Gray is used for empty/pending states.
- Audit is secondary; it must not compete with the main pre-flight form.

## Copy Rules

Use:

- `Pre-flight check`
- `Trading request`
- `Injective account`
- `Agent decision`
- `Simulate safer trade`
- `Recorded on Injective testnet`
- `Verified matched`
- `No order was placed`

Do not use in Injective mode:

- `MantleLens`
- `Mantle Sepolia`
- `Mantlescan`
- `Wallet Guard`
- `approval anomaly` unless the scenario is specifically about permissions
- `revoke`
- `swap`
- `Replay proof only` for live checks
