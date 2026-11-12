# Distributed Loop: ORCA D1 Global HOLD integration

The legacy `.github/workflows/distributed-autonomous-loop.yml` now checks the ORCA D1 Global HOLD endpoint before any loop work and rechecks immediately before the task runner, GitHub branch publication, durable completion-state writes, Recovery AI state writes, and the external Google Sheets ledger.

## Required GitHub Actions secrets

- `ORCA_TASK_API_URL`: base URL of the deployed ORCA D1 Worker (for example, the Worker origin; do not append `/control/global-hold`).
- `ORCA_TASK_API_TOKEN`: bearer token accepted by that Worker.

Both secrets are required. If either is missing, the endpoint is unavailable, the response is malformed, or the returned state is not exactly `clear=true`, `value="off"`, and `blocked=false`, the workflow fails closed and reports `BLOCKED`. There is no local fallback and no default-off behavior.

## Gate placement

1. Initial gate runs directly after checkout, before state reads, task selection, model execution, or queue refill.
2. A second gate runs immediately before the bounded task runner.
3. Further gates run immediately before publishing a development branch and before durable state / Recovery AI / Sheets writes.
4. A HOLD failure creates a local marker so the final report records `BLOCKED: orca_global_hold_active_or_unavailable`.
5. Sheets ledger writes are skipped if the last Global HOLD check did not pass. Final status/report notifications and artifact upload remain available for observability; they do not authorize task execution.

## Important limitations

- This is a fail-closed preflight, not an atomic transaction with GitHub. D1 HOLD can change after a successful read and before a GitHub write (TOCTOU). Rechecks narrow but do not eliminate that race.
- A strong guarantee against the race requires a write broker/lease whose authorization and write operation are enforced in one trusted boundary. Until then, this workflow must not be treated as race-free.
- The check does not release Global HOLD, alter D1, deploy a Worker, or configure repository secrets.
- Before merging, an operator must configure and verify the two Actions secrets and review the expected behavior if the old workflow is triggered while HOLD is ON or secrets are absent.
- Keep PR #1331 unmerged until the replacement distributed-loop executor is verified and the legacy workflow cutover is explicitly approved.
