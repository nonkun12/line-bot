# ORCA distributed loop: 30-minute cadence

## What this change does

- Changes the existing distributed autonomous loop target from hourly to every 30 minutes at :07 and :37 Japan time.
- Adds a read-only gate job before the existing loop executor.
- Serializes runs with the existing distributed-autonomous-loop concurrency group.
- Checks the latest previous main-branch run and drops a scheduled or automatic continuation invocation when 30 minutes have not elapsed. A delayed run is not replayed as a burst.
- Keeps scheduled runs at one task per tick. Manual bounded runs remain capped at four.
- Does not alter the separate minutely notification-outbox Cron in wrangler.toml.example.

GitHub scheduling is best-effort: it can be delayed or skipped. This is a 30-minute target, not an exact-time guarantee.

## Required live safety endpoints

The gate fails closed unless all of these are configured and return valid, fresh data:

1. ORCA_TASK_API_URL and ORCA_TASK_API_TOKEN: authenticated GET /control/global-hold must return exactly clear=true, value="off", and blocked=false.
2. ORCA_BUDGET_GATE_URL and ORCA_BUDGET_GATE_TOKEN: authenticated GET must return a JSON object with sources, containing one enabled snapshot each for cloudflare_workers, cloudflare_d1, and github_actions.

Each snapshot must include used, positive verified limit, unit, limit_source, observed_at, period_start, and period_end. Values must use consistent units within each source. The response must also include a non-negative consecutive_failures integer; three or more blocks execution. Snapshots must be no older than 90 minutes, no more than five minutes in the future, and cover the current period.

Thresholds are conservative internal policy, not vendor quota guarantees:
- 70%: WARN; may continue with fresh evidence.
- 80%: SUPPRESS; block new work.
- 90%: STOP; block new work.
- Missing, unknown, or stale data: BLOCKED.

The budget endpoint and provider collectors are not part of this PR. Until a trusted live collector provides the contract above, scheduled and manual runs are blocked by design. Do not set dummy values or bypass the gate.

## Remaining rollout dependency

This PR uses the existing GitHub Actions concurrency group plus the previous main-branch workflow-run history as a serialized 30-minute guard. It does not add the D1 atomic slot ledger described in the broader ORCA rollout plan. Keep this as the sole automatic loop scheduler; if another independent scheduler/dispatcher is introduced, add and verify a shared durable slot ledger before activation.

## Runtime limits and safety

- Scheduled run: one task per tick (within the four-task policy ceiling).
- Automatic Chain Job AI continuations are also throttled to the same 30-minute minimum. Explicit manual starts (depth-zero workflow dispatch, owner issue-comment, or owner PR label) may start outside cadence but must pass HOLD and budget gates.
- Existing task-level SafetyGate, Recovery HOLD, Global HOLD checks, evidence requirements, and no-auto-merge/no-deploy rules remain in place.
- AUTO_APPLY_PATCH=false and AUTO_DEPLOY=false remain unchanged.
- This change does not apply migrations, configure secrets, dispatch Actions, deploy, merge, or release HOLD.
- The schedule becomes active only after this Draft PR and its dependency chain are reviewed and merged. No activation is performed here.
