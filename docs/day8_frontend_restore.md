# Day 8 Frontend Restore

Day 8 closes the refresh/restart gap for the demo path.

Before this step, Day 7 persisted the latest assessment and proof state on the backend, but a freshly opened browser still started from the empty frontend state. That made the verified proof feel fragile during a judge walkthrough.

## What Changed

- Added `GET /api/injective/preflight/latest`.
- The endpoint returns the latest persisted pre-flight assessment, including proof state.
- If no persisted assessment exists, it returns `404 not_found`.
- The frontend calls the latest endpoint once on page load.
- When a latest assessment exists, the frontend restores:
  - assessment result
  - prompt and account fields
  - proof status
  - history records
  - decision audit trace

## Demo Behavior

The intended judge path is now:

```text
Run agent guard check
-> Record proof
-> Verify proof
-> Restart API or refresh browser
-> Frontend restores the verified matched assessment
```

The restored proof still means only:

```text
the local assessment hash matches the recorded assessment hash
```

It does not claim that a trade is profitable, safe, or executed.

## Acceptance Criteria

- `GET /api/injective/preflight/latest` returns `404` before any assessment is persisted.
- After record and verify, restarting the backend and calling latest returns the same assessment with `proof.status = verified_matched`.
- Browser refresh restores the latest assessment instead of showing the empty state.
- History and Decision Audit continue to reflect the restored proof state.
- No private key, seed phrase, auto-signing, transfer, or order placement path is introduced.
