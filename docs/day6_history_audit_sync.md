# Day 6 History and Audit Sync Completion

## Objective

Make History and Audit consume backend endpoints instead of frontend-derived state wherever possible, so recorded and verified proof state remains consistent after record/verify and tab changes.

## Delivered

- Added frontend API calls:
  - `GET /api/history/preflight`
  - `GET /api/agent/audit`
- Removed frontend `initialHistory` local history construction.
- Added `historyRecords` state populated from the backend history endpoint.
- Added `audit` state populated from the backend audit endpoint.
- `Run agent guard check` now refreshes backend history and audit after assessment creation.
- `Record proof` now refreshes backend history and audit after proof recording.
- `Verify proof` now refreshes backend history and audit after proof verification.
- Opening the History tab refetches backend history.
- Opening the Audit panel refetches backend audit.
- Audit tool trace now comes from the backend endpoint, not the local assessment fallback when backend data is available.
- Health metadata now reports:

```json
{
  "day": "6",
  "mode": "day6-history-audit-api"
}
```

## Consistency Behavior

After pre-flight:

```text
History proof: Assessment hash generated
Audit VerifyAssessment: skipped
```

After record:

```text
History proof: Proof recorded on Injective testnet
Audit RecordAssessment: completed
```

After verify:

```text
History proof: Proof verified · recorded hash matches
Audit VerifyAssessment: completed
```

## Verification

Backend/static:

```bash
python3 -m unittest tests.test_injective_day3_api tests.test_injective_day4_adapters tests.test_injective_day5_proof tests.test_injective_day6_history_audit -v
```

Result:

```text
Ran 13 tests
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
  "day6Status": true,
  "preflightHit": true,
  "historyHitAfterRun": true,
  "auditHitAfterRun": true,
  "localReplay": true,
  "recordHit": true,
  "verifyHit": true,
  "historyHitAfterTab": true,
  "historyBackendProof": true,
  "auditHitAfterTab": true,
  "auditBackendTrace": true,
  "noMantleProductCopy": true,
  "hits": {
    "preflight": 1,
    "record": 1,
    "verify": 1,
    "history": 4,
    "audit": 4
  }
}
```

## Files Changed

- `frontend/app/src/injectivePreflightApi.ts`
- `frontend/app/src/App.tsx`
- `backend/injectivelens/server.py`
- `tests/test_injective_day6_history_audit.py`

## Day 7 Starting Point

Day 7 should add a small persistence boundary for the latest assessment/proof history, so backend history survives server restart during demo rehearsal.
