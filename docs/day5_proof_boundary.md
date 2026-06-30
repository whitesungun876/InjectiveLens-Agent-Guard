# Day 5 Proof Boundary Completion

## Objective

Add a proof recorder and verification boundary for Injective while keeping the default flow no-signing, no-private-key, and no-broadcast. Proof status must be explicit and must not imply trade safety.

## Delivered

- Added `backend/injectivelens/proof.py`.
- Added explicit proof states:
  - `ready_to_record`
  - `pending`
  - `recorded`
  - `verified_matched`
  - `unavailable`
- Changed pre-flight behavior so assessments are not auto-recorded or auto-verified.
- Added `POST /api/proof/record`.
- Added explicit confirmation requirement:

```text
confirmation = user_confirmed_record_assessment
```

- Changed `POST /api/proof/verify` so it only verifies recorded proofs.
- Updated History and Audit proof status after record/verify.
- Updated frontend proof workflow:
  - pre-flight shows Injective testnet proof readiness;
  - verify is disabled before record;
  - record proof calls `/api/proof/record`;
  - verify proof calls `/api/proof/verify`;
  - verified matched propagates to Overview, Evidence, History, and Audit.
- Updated `.env.example` with:

```bash
INJECTIVE_PROOF_RECORDER_MODE=external_tx
INJECTIVE_PROOF_TX_HASH=
```

## Safety Boundary

Day 5 still does not:

- request private keys;
- request seed phrases;
- connect a wallet;
- auto-sign;
- broadcast transactions;
- place orders;
- transfer funds.

The proof recorder requires explicit confirmation and proves only the assessment record hash, not trade safety or profitability. Without `INJECTIVE_PROOF_TX_HASH`, record returns `pending` instead of pretending an Injective transaction exists.

## API Behavior

### Pre-flight

`POST /api/injective/preflight`

Demo mode returns:

```text
proof.status = ready_to_record
proof.proofMethod = tx_memo
proof.txHash = null
```

### Record

`POST /api/proof/record`

Without explicit confirmation:

```text
400 confirmation_required
```

With explicit confirmation:

```text
proof.status = pending
proof.recordedAssessmentHash = assessmentHash
```

After `INJECTIVE_PROOF_TX_HASH` is configured:

```text
proof.status = recorded
proof.txHash = <injective-testnet-tx-hash>
```

### Verify

`POST /api/proof/verify`

Before recording:

```text
status = not_found
```

After recording:

```text
status = verified_matched
```

## Verification

Backend:

```bash
python3 -m unittest tests.test_injective_day3_api tests.test_injective_day4_adapters tests.test_injective_day5_proof -v
```

Result:

```text
Ran 11 tests
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
  "day5Status": true,
  "preflightHit": true,
  "localReplay": true,
  "verifyDisabledBeforeRecord": true,
  "recordHit": true,
  "recorded": true,
  "verifyEnabledAfterRecord": true,
  "verifyHit": true,
  "verifiedMatched": true,
  "evidenceProof": true,
  "historyProof": true,
  "auditProof": true,
  "noMantleProductCopy": true
}
```

## Files Changed

- `backend/injectivelens/proof.py`
- `backend/injectivelens/fixtures.py`
- `backend/injectivelens/server.py`
- `backend/injectivelens/__init__.py`
- `frontend/app/src/injectivePreflightApi.ts`
- `frontend/app/src/App.tsx`
- `frontend/app/src/styles.css`
- `tests/test_injective_day3_api.py`
- `tests/test_injective_day5_proof.py`
- `.env.example`
- `README.md`
- `docs/day1/02_api_contract.openapi.yaml`

## Day 6 Starting Point

Day 6 should make history and audit consume backend endpoints instead of local frontend-derived history where possible, so recorded/verified proof state remains consistent after refresh.
