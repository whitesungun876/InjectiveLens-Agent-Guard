# Migration Notes

This folder was created from the existing MantleLens codebase as a clean workspace for the Injective Nova project.

## What Was Copied

- Backend package from `backend/`
- Frontend app from `frontend/app/`, excluding `node_modules`, `dist`, and `.vercel`
- Contracts from `contracts/`
- Scripts from `scripts/`
- Tests from `tests/`
- Injective Day 1 docs from `docs/injective/day1/`
- Environment examples and Python requirements

## What Has Not Been Migrated Yet

The copied implementation still contains Mantle-specific module names, fixtures, tests, and contracts. Those are intentionally preserved as a working base, not as final Injective behavior.

Day 2 should begin by introducing:

- `TradeIntent`
- `PreflightAssessment`
- Injective demo scenarios
- Injective account / market / position evidence
- Injective proof record and verification stubs
- UI copy and state aligned with `docs/day1/03_information_architecture_wireframe.md`

## Do Not Ship Until

- Main UI no longer presents Mantle as the active chain.
- History and proof status use Injective terminology.
- Tests reflect Injective pre-flight risk behavior.
- README and demo video point to Injective integration.
