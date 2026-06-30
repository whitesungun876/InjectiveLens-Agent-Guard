# Day 2 Frontend Mock Pre-flight Completion

## Objective

Convert the copied frontend into an Injective trading pre-flight check experience.

## Delivered

- Overview structure for natural-language trading request review.
- Evidence structure for account, market, position, and source coverage claims.
- History structure for recent pre-flight assessments with independent proof status.
- Audit structure for agent decision, allowed/blocked actions, LLM boundary, and MCP-style tool trace.
- Mock pre-flight data that runs the full path without backend dependency.

## Standard Mock Scenario

```text
Open a 10x long INJ-PERP using 60% of available margin.
```

Expected result:

```text
Decision: BLOCK
Risk score: 86 / 100
Action: Block execution and simulate safer trade
Proof: Recorded on Injective testnet / verified matched
```

## Frontend Acceptance

| Requirement | Evidence |
|---|---|
| Page is pre-trade check, not wallet scan | Header and first card use InjectiveLens / pre-flight trading request copy |
| Overview exists | Shows BLOCK hero, risk score, parsed intent, core risk signals, workflow actions |
| Evidence exists | Shows evidence bundle, risk evidence, and supporting records |
| History exists | Shows recent pre-flight assessments and proof status |
| Audit exists | Shows decision audit, allowed/blocked actions, MCP-style tool trace, LLM boundary |
| Mock data runs end-to-end | Playwright smoke test clicks Run -> Overview -> Evidence -> History -> Audit |
| No main-path Mantle branding | Smoke test verifies Overview does not show `MantleLens Wallet Guard` or `Mantle Sepolia` |

## Verification Command

From `InjectiveLens Agent Guard/frontend/app`:

```bash
npm install
npm run build
npm run dev -- --host 127.0.0.1 --port 5183
```

Smoke test result:

```json
{
  "loadedTitle": true,
  "overviewBlock": true,
  "overviewSimulation": true,
  "overviewProof": true,
  "evidenceBundle": true,
  "historyRecords": true,
  "auditDecision": true,
  "noMantleHero": true
}
```

## Files Changed

- `frontend/app/src/App.tsx`
- `frontend/app/src/styles.css`
- `docs/day2_frontend_mock_preflight.md`

## Day 3 Starting Point

Day 3 should replace the current in-memory mock builder with:

- `TradeIntent` parser module.
- Backend fixture endpoint matching `docs/day1/02_api_contract.openapi.yaml`.
- Demo scenarios served through an API shape matching `PreflightAssessment`.
