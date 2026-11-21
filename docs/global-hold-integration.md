# Global HOLD integration boundary

This PR keeps the legacy GitHub Actions autonomous-development entry points
fail-closed with an empty event allowlist. The local `ImmediateStopController`
is a secondary process latch; it is not the authoritative cross-runner state.

The ORCA D1 worker is a separate execution path and must not rely on that local
latch. Its independent enforcement is implemented across the companion PRs:

- #1332 checks the authenticated D1 Global HOLD endpoint before polling,
  processing, claiming, staging, committing, pushing, and creating a PR.
- #1333 adds the D1 `system_controls` row, initialized to
  `global_hold=on`, and enforces the positive allow condition
  `value='off'` in intake, approval, claim, and outbox dispatch.

The integration is not production-active until #1332 and #1333 are reviewed,
the migration is applied by an authorized human, and the Worker deployment is
separately approved. Missing D1 state remains HOLD. No AI or timeout can release
the hold. This PR does not deploy, change production D1, or grant new permissions.
