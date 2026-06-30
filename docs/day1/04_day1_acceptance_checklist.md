# InjectiveLens Day 1 Acceptance Checklist

## Day 1 Objective

Complete scope and information architecture for the full InjectiveLens Agent Guard build.

Day 1 is complete only if the team can start Day 2 frontend/backend implementation without re-litigating product scope, data objects, demo flow, or safety boundaries.

## Required Artifacts

| Artifact | Path | Required | Status |
|---|---|---:|---|
| Scope lock / PRD seed | `docs/injective/day1/01_scope_lock.md` | Yes | Complete |
| API and data contract | `docs/injective/day1/02_api_contract.openapi.yaml` | Yes | Complete |
| Information architecture / wireframe | `docs/injective/day1/03_information_architecture_wireframe.md` | Yes | Complete |
| Acceptance checklist | `docs/injective/day1/04_day1_acceptance_checklist.md` | Yes | Complete |

## Product Scope Acceptance

| Requirement | Pass Criteria | Status |
|---|---|---|
| Product is Injective-native | Describes AI trading pre-flight on Injective, not Mantle wallet scanning | Pass |
| Main user path fixed | Natural-language trade request -> decision -> simulation -> proof -> history | Pass |
| P0/P1/P2 separated | P0 excludes real order placement and key custody | Pass |
| Safety boundaries explicit | No private keys, no seed phrases, no auto-sign, no transfers, no default order placement | Pass |
| Demo request fixed | Standard high-risk prompt is documented | Pass |
| Proof scope clear | Assessment proof is not profit proof or safety guarantee | Pass |

## API Contract Acceptance

| Requirement | Pass Criteria | Status |
|---|---|---|
| Trade intent model exists | `TradeIntent` includes market, side, order type, leverage, margin usage | Pass |
| Preflight endpoint exists | `/api/injective/preflight` returns full assessment | Pass |
| Read-only Injective data endpoints exist | Account, market, and positions endpoints are defined | Pass |
| Risk endpoint exists | `/api/risk/evaluate-trade` returns allow/warn/block | Pass |
| Simulation endpoint exists | `/api/simulation/safer-trade` returns before/after and `noBroadcast: true` | Pass |
| Proof endpoints exist | `/api/proof/record` and `/api/proof/verify` are defined | Pass |
| History endpoint exists | `/api/history/preflight` returns independent proof status per record | Pass |
| Audit endpoint exists | `/api/agent/audit` returns decision and tool trace | Pass |
| Error handling exists | Bad request and source unavailable responses are defined | Pass |

## UI / IA Acceptance

| Requirement | Pass Criteria | Status |
|---|---|---|
| Overview is pre-flight first | First screen centers natural-language trading request and risk decision | Pass |
| Evidence is risk-centered | Account, market, position, and coverage evidence support claims | Pass |
| History is assessment-centered | Recent pre-flight records show independent proof status | Pass |
| Audit proves agentic loop | Decision, allowed/blocked actions, tool trace, and LLM boundary are visible | Pass |
| Empty/loading/error states exist | Copy is defined for first-time, loading, low-confidence, and error states | Pass |
| Visual hierarchy defined | Color and emphasis rules are documented | Pass |
| Forbidden copy listed | Mantle / Mantlescan / revoke / wallet-guard copy is blocked in Injective mode | Pass |

## Demo Readiness Acceptance

| Requirement | Pass Criteria | Status |
|---|---|---|
| Demo can be explained in 3 minutes | Flow has 8 fixed steps from prompt to proof | Pass |
| High-risk request blocks execution | Standard prompt must return `BLOCK` | Pass |
| Safer simulation is available | Reduced leverage/margin alternative is part of P0 | Pass |
| Proof is part of demo | Recorded and verified Injective proof is required for standard MVP | Pass |
| No accidental trading path | UI/API spec has no order placement endpoint in P0 | Pass |

## Day 2 Inputs

Day 2 implementation should start with:

1. New product constants:
   - `InjectiveLens Agent Guard`
   - `A safety and proof layer before AI agents execute trades on Injective`
2. Frontend mock data based on `PreflightAssessment`.
3. Backend stub endpoints matching `02_api_contract.openapi.yaml`.
4. Demo scenario:
   - `Open a 10x long INJ-PERP using 60% of available margin.`
5. Risk decision fixture:
   - `decision = block`
   - `riskScore >= 80`
   - `riskLevel = critical`
   - `blockedActions` includes `place order`, `auto-sign`, `transfer funds`
6. Simulation fixture:
   - Before: `10x`, `60% margin usage`
   - After: `3x`, `15% margin usage`
   - `noBroadcast = true`

## Scope Cut Gate

If time collapses, preserve these P0 pieces:

```text
Natural-language request
Parsed trade intent
Deterministic block decision
Evidence-bound risk claims
Safer simulation
Injective proof record
Verified matched proof
```

Cut first:

```text
Agent identity registry
Full MCP execution
Multi-market selector
Azure OpenAI
CosmWasm logger if tx memo proof is ready
```

## Day 1 Completion Decision

Day 1 is accepted when:

- All four Day 1 artifacts exist.
- Product scope is Injective-native.
- API contract supports the complete MVP loop.
- Wireframe defines all main pages and states.
- No P0 path requires real trading, private key custody, or auto-signing.

Decision: **Accepted for Day 2 implementation.**
