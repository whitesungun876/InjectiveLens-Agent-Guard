# Day 4 Read-only Injective Adapter Completion

## Objective

Replace the Day 3 fixture-only account, market, and position source path with an adapter layer that can use real read-only Injective endpoints when configured, while preserving the existing `PreflightAssessment` API contract and safety boundaries.

## Delivered

- Added `backend/injectivelens/adapters.py`.
- Added `FixtureInjectiveReadOnlyAdapter` for deterministic demo scenarios.
- Added `LiveInjectiveReadOnlyAdapter` for configured read-only HTTP sources.
- Added source coverage merging across account, market, and positions.
- Updated `build_preflight_assessment` to use adapters instead of calling fixture functions directly.
- Updated `/api/injective/account`, `/api/injective/market`, and `/api/injective/positions` to use the selected adapter.
- Updated health metadata to `day = 4`.
- Updated frontend status copy to `Day 4 read-only adapter ready`.
- Updated `.env.example` with Injective read-only endpoint settings.

## Live Read-only Configuration

Optional environment variables:

```bash
INJECTIVE_LCD_REST_URL=
INJECTIVE_MARKET_SNAPSHOT_URL=
INJECTIVE_POSITIONS_URL=
INJECTIVE_READ_TIMEOUT_SECONDS=3
```

The LCD adapter reads balances via:

```text
GET {INJECTIVE_LCD_REST_URL}/cosmos/bank/v1beta1/balances/{address}
```

Market and positions endpoints are provider-specific URL templates. They can use:

```text
{market}
{network}
{subaccount_id}
```

## Safety Behavior

If a live endpoint is not configured or fails:

- the API still returns the same `PreflightAssessment` shape;
- the affected source becomes `partial`;
- unavailable sources are listed;
- unknown fields are listed;
- missing live data is treated as unknown rather than safe;
- even a low-leverage live prompt can be blocked if source coverage is partial.

No Day 4 path requests private keys, seed phrases, wallet connection, signing, transfer, or order placement.

## Verification

Backend:

```bash
python3 -m unittest tests.test_injective_day3_api tests.test_injective_day4_adapters -v
```

Result:

```text
Ran 7 tests
OK
```

Browser smoke:

```json
{
  "loadedTitle": true,
  "day4Status": true,
  "apiHit": true,
  "overviewBlock": true,
  "overviewSignals": true,
  "overviewSimulation": true,
  "overviewProof": true,
  "evidenceBundle": true,
  "historyTrend": true,
  "auditDecision": true,
  "auditTrace": true,
  "noMantleProductCopy": true
}
```

## Files Changed

- `backend/injectivelens/adapters.py`
- `backend/injectivelens/fixtures.py`
- `backend/injectivelens/server.py`
- `backend/injectivelens/__init__.py`
- `backend/injectivelens/parser.py`
- `frontend/app/src/App.tsx`
- `tests/test_injective_day4_adapters.py`
- `.env.example`
- `README.md`

## Day 5 Starting Point

Day 5 should add a proof recorder/verification boundary for Injective. Keep the current no-signing default, but make proof status explicit:

- local replay proof;
- ready to record;
- recorded;
- verified matched;
- unavailable.
