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
2. ORCA_BUDGET_GATE_URL and ORCA_BUDGET_GATE_TOKEN: authenticated GET must return a signed evidence envelope containing one enabled snapshot each for cloudflare_workers, cloudflare_d1, and cloudflare_durable_objects. ORCA_BUDGET_EVIDENCE_HMAC_KEY must be configured in both the trusted collector and GitHub Actions.

Each signed envelope must contain `schema_version=1`, `collector_id="orca-budget-collector"`, a stable account ID, `observed_at`, current quota `period_start`/`period_end`, a non-negative `consecutive_failures` count, and exactly the three required source records. Its HMAC-SHA256 signature covers the canonical JSON payload excluding the signature field. Each source record must include used, positive limit, unit, source API, limit source/evidence ID, `quality="exact"`, `coverage_complete=true`, `exact_counter=true`, `sampling_mode="none"`, resource count/digest, and a source watermark. The verifier rejects absent/invalid signatures, missing/extra sources, incomplete coverage, sampling, stale/future watermarks, and stale snapshots. Snapshot and watermark freshness are limited to 10 minutes; future skew is limited to five minutes. The collector signing key must be held only by the trusted collector and verifier; never place it in repository files or task payloads.

Thresholds are conservative internal policy, not vendor quota guarantees:
- 70%: WARN; may continue with fresh evidence.
- 80%: SUPPRESS; block new work.
- 90%: STOP; block new work.
- Missing, unknown, or stale data: BLOCKED.

The signed-evidence verifier is part of this fix branch, but the trusted live collector/writer is not yet implemented. Until it can produce independently validated exact, complete, account-wide evidence, scheduled and manual runs are blocked by design. Do not set dummy values or bypass the gate.

## Remaining rollout dependency

This PR uses the existing GitHub Actions concurrency group plus the previous main-branch workflow-run history as a serialized 30-minute guard. It does not add the D1 atomic slot ledger described in the broader ORCA rollout plan. Keep this as the sole automatic loop scheduler; if another independent scheduler/dispatcher is introduced, add and verify a shared durable slot ledger before activation.

## Runtime limits and safety

- Scheduled run: one task per tick (within the four-task policy ceiling).
- Automatic Chain Job AI continuations are also throttled to the same 30-minute minimum. Explicit manual starts (depth-zero workflow dispatch, owner issue-comment, or owner PR label) may start outside cadence but must pass HOLD and budget gates.
- Existing task-level SafetyGate, Recovery HOLD, Global HOLD checks, evidence requirements, and no-auto-merge/no-deploy rules remain in place.
- AUTO_APPLY_PATCH=false and AUTO_DEPLOY=false remain unchanged.
- This change does not apply migrations, configure secrets, dispatch Actions, deploy, merge, or release HOLD.
- The schedule becomes active only after this Draft PR and its dependency chain are reviewed and merged. No activation is performed here.

## Budget observation contract (follow-up)

The observation record helper in `scripts/distributed_loop_budget_observation.py` is not a live provider collector. It normalizes measured values for reporting only and forcibly emits:

- `enforcement_eligible=false`
- `limit_verified=false`
- `limit=null` and `limit_evidence_id=null`

Caller-supplied limit values and authority flags are discarded. An `exact` measurement describes measurement quality only; it does not prove that the vendor quota or billing limit is authoritative. Observation records must never be passed as enforcement snapshots. The gate now rejects missing or unverified enforcement evidence with `budget_limit_not_authoritatively_verified`.

No live Workers/D1/GitHub usage collector, budget endpoint, provider credentials, deployment, or secret configuration is added here. The 30-minute loop remains blocked until independently verified enforcement evidence is available.


## In-flight stop monitoring

The loop runner accepts a stop file and terminates the active child process group when that file appears. The 30-minute workflow starts a dedicated watcher that rechecks remote stop state, Global HOLD, and the signed Budget Guardian gate every 15 seconds. Any failed request, stale/invalid evidence, or unknown state creates the stop file. A supervisor also creates the stop file if the watcher process exits unexpectedly. This remains fail-closed; the watcher does not release a latched STOP.
