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

The workflow now requires three independent checks before task execution: `/control/global-hold`, `/control/loop-admission`, and the signed schema-v2 meter endpoint. `/control/loop-admission` must return HTTP 200 with `allowed=true`, Global HOLD `clear=true/value=off/blocked=false/unresolved_operations=0`, and Budget Guardian `allowed=true/status=CLEAR|WARN`. This endpoint also represents the D1 STOP-latch decision; a missing endpoint, missing token, HTTP 423, or malformed response is BLOCKED.

The same admission endpoint is polled every 15 seconds during execution and rechecked immediately before task publication and durable-state writes. The separate `ORCA_CONTROL_API_URL` and `ORCA_LOOP_PREFLIGHT_TOKEN` GitHub secrets are required. The endpoint implementation is currently in Draft PR #1344 and is not present in this branch's Worker source; until that dependency is reviewed and integrated, this workflow is expected to remain BLOCKED.
The gate fails closed unless all of these are configured and return valid, fresh data:

1. ORCA_TASK_API_URL and ORCA_TASK_API_TOKEN: authenticated GET /control/global-hold must return exactly clear=true, value="off", and blocked=false.
2. ORCA_BUDGET_GATE_URL and ORCA_BUDGET_GATE_TOKEN: authenticated GET must return schema version 2 with a signed `meter_inventory` and `meters` array. The inventory must declare complete account coverage, the expected Cloudflare and GitHub account IDs, exactly the currently supported enabled products (`workers`, `workers_logs`, `d1`, `durable_objects`, `actions`, `actions_packages`), no unresolved products, and fresh inventory observation/watermark timestamps. Any newly discovered or unsupported product blocks execution until its dimensions are added to the allowlist.

Schema v2 requires one unique meter record for each of these independent dimensions:

- `cloudflare.workers.requests.daily`
- `cloudflare.workers.cpu_ms_per_invocation.max`
- `cloudflare.workers_logs.events.daily`
- `cloudflare.d1.rows_read.daily`, `cloudflare.d1.rows_written.daily`, `cloudflare.d1.storage_bytes.total`
- `cloudflare.durable_objects.requests.daily`, `cloudflare.durable_objects.duration_gb_seconds.daily`, `cloudflare.durable_objects.sqlite_rows_read.daily`, `cloudflare.durable_objects.sqlite_rows_written.daily`, `cloudflare.durable_objects.sqlite_storage_bytes.total`
- `github.actions.compute_cost_usd.monthly`, `github.actions_packages.shared_storage_gb_hours.monthly`, `github.actions.cache_storage_bytes.hourly_peak`

Each meter must include provider, product, account ID, enabled status, used quantity, positive authoritative limit, exact unit, limit source/evidence ID, exactness and complete-coverage flags, no-sampling declaration, observation time, source watermark, and `period_kind`. The signed inventory must also attest `github_repository_visibility=public` and `github_runner_policy=standard_github_hosted_only`. Independently, the gate queries GitHub repository metadata and scans this loop workflow's `runs-on` declarations; it accepts only a non-archived public repository and standard Ubuntu GitHub-hosted runner labels. Private repositories, larger runners, self-hosted runners, or dynamic runner labels in this loop workflow are BLOCKED. This check covers the current loop workflow; the account-wide compute meter must still cover other private repositories and any other billable runner/Sandbox usage. Daily/monthly meters must also provide current period boundaries. Total-capacity and per-invocation meters must not claim reset-period boundaries. The response must include a non-negative `consecutive_failures` integer; three or more blocks execution. All inventory and meter watermarks must be no older than 10 minutes and no more than five minutes in the future.

Thresholds are conservative internal policy, not vendor quota guarantees:
- 70%: WARN; may continue with fresh evidence.
- 80%: SUPPRESS; block new work.
- 90%: STOP; block new work.
- Missing, unknown, or stale data: BLOCKED.

The entire response, including the product inventory and all meter records, must carry an `attestation` object signed with HMAC-SHA256 over canonical JSON with only the signature field removed. The signed attestation binds `account_id`, `collector_id`, `issued_at`, and `expires_at`; the gate checks the expected account and collector IDs, signature, a maximum 15-minute attestation lifetime, and a 10-minute issue-time freshness window. Every meter declares provider/account scope, complete coverage, exact counter semantics, no sampling, dataset identity, and a current source watermark. The workflow reads `ORCA_BUDGET_EVIDENCE_HMAC_SECRET` from a GitHub Secret and the expected Cloudflare account, GitHub billing account, and collector IDs from repository Variables. Missing configuration, invalid signatures, unknown products, partial coverage, sampling, or stale watermarks BLOCK execution.

The trusted live collector and signed budget endpoint are not part of this branch. Until they exist and produce independently verifiable evidence, scheduled and manual runs are blocked by design. Do not set dummy values or bypass the gate.


## Multi-dimension quota inventory and account scope

Schema v2 replaces the earlier four-product-row contract with unique `meter_id` records and a signed account product inventory. The current allowlist deliberately covers only Workers, Workers Logs, D1, SQLite Durable Objects, and GitHub Actions. If the inventory discovers any additional enabled product (for example KV, Hyperdrive, Queues, Workflows, R2, or Vectorize), the gate blocks until that product's full set of independent dimensions is added and validated.

Minimum dimensions to model when the corresponding product is enabled (verify the account's current plan and product-specific terms before assigning a limit):

| Product | Separate dimensions / constraints |
|---|---|
| Workers / Pages Functions | Incoming Worker requests per day; per-invocation CPU ceiling (not a shared daily percentage); Worker count / other account-level hard limits where relevant |
| Workers Logs | Log events written per day and retention |
| D1 | Rows read per day; rows written per day; aggregate account storage; database count |
| Durable Objects (SQLite) | Requests per day; active non-hibernated duration in GB-seconds per day; SQLite rows read/written per day; aggregate SQL storage |
| Workers KV (if enabled) | Reads, writes, deletes, list operations per day; stored data; namespace count |
| Hyperdrive (if enabled) | Database queries per day |
| Queues (if enabled) | Operations per day, including write/read/delete and retry effects; queue count |
| Workflows (if enabled) | Requests shared with Workers; per-invocation CPU ceiling; storage; steps per day |
| R2 (if enabled) | Stored GB-months; Class A operations; Class B operations |
| Vectorize / other usage products (if enabled) | Every product-specific query, storage, dimension, or compute meter, with its own unit and period |
| GitHub Actions | Account-wide private/internal/larger-runner compute cost in USD; shared Actions-artifact/GitHub-Packages storage in GB-hours; per-repository Actions cache peak storage. Standard hosted runners in this public repo are free, but other private repositories share the account compute allowance |

Cloudflare's current published pricing lists these dimensions separately. Examples include Workers request quota and per-invocation CPU, D1 rows read/written/storage, Durable Objects requests/duration/SQLite storage, and separate KV, Hyperdrive, Queues, Workflows, and R2 dimensions. Free daily quotas reset at 00:00 UTC; monthly periods have their own boundaries. See https://developers.cloudflare.com/workers/platform/pricing/ and https://developers.cloudflare.com/workers/platform/limits/.

The `line-bot` repository is confirmed public and its current loop workflow uses only standard `ubuntu-latest` runners, so this workflow's own runner compute is free. However, the linked GitHub account also owns private repositories; their standard runners, internal-repository runners, larger runners, and cloud sandbox can draw from the account-wide included compute pool. Schema v2 therefore retains an account-wide `github.actions.compute_cost_usd.monthly` meter and must not infer zero from this repository's public status. Larger runners are disallowed in the loop workflow. Actions artifact storage shares an account allowance with GitHub Packages; Actions cache storage has a separate per-repository allowance. The repository cache-usage API refreshes approximately every five minutes, but returns current active cache size while billing uses hourly peak usage; a collector must retain a complete per-hour high-water mark and fail closed on gaps. Artifact-storage usage is updated within 6–12 hours, which does not satisfy this gate's 10-minute freshness rule. The collector must not pretend that a billing report or poll timestamp makes that data real-time; until an exact fresh source exists, the shared-storage meter remains BLOCKED. See https://docs.github.com/en/actions/how-tos/write-workflows/choose-where-workflows-run/choose-the-runner-for-a-job, https://docs.github.com/en/billing/concepts/product-billing/github-actions, and https://docs.github.com/en/rest/actions/cache.

The authenticated writer that updates D1 `budget_guard_state` must calculate the worst status across **all** schema-v2 meters, including GitHub storage, and set `stop_latched=1` when any meter reaches 90%. That latch must remain set across quota resets or later lower readings until a separately authenticated human release. PR #1344's current pure evaluator covers the three Cloudflare domains only; its writer/integration must be extended or composed with the GitHub storage meters before its D1 status can represent the complete schema-v2 budget. The per-run HMAC gate is not a substitute for persistent STOP latching.

Required schema-v2 rules:
- Each meter has a unique immutable `meter_id`, provider/account identity, product/SKU, unit, authoritative limit evidence, exact used quantity, period start/end, observation time, and source watermark.
- The signed account inventory must enumerate all enabled billable products and all their dimensions; unknown products, missing dimensions, duplicate meter IDs, partial pagination, or unresolved product inventory are BLOCKED. For GitHub, it must attest the public-repository and standard-hosted-runner policy, and include the Actions/Packages shared-storage and Actions cache meters.
- Each meter is evaluated independently. Do not combine requests, rows, storage, duration, steps, money, or runner SKUs into one percentage.
- Per-invocation hard ceilings are enforced at the individual task/runtime boundary, not averaged into an account-level daily quota.
- The HMAC binds the entire inventory and meter array. A collector assertion alone is not sufficient unless its provider query, coverage, pagination, freshness, and exactness have been independently validated.
- The gate now parses schema v2 and tests per-meter inventory completeness. No production collector or signed endpoint emits this contract yet; v1 four-row payloads are rejected. Schema v2 is not production-admissible until its collector, authoritative provider coverage, and boundary tests are independently verified.

## Cloudflare telemetry admissibility findings (2026-11-13)

The provider documentation does not currently establish a free, account-wide, exact, unsampled usage counter with a watermark no older than ten minutes for all required meters:

- Cloudflare's GraphQL Analytics API is an analytics interface, not a billing meter. Cloudflare explicitly says GraphQL analytics should not be used as a measure of usage Cloudflare uses for billing. See https://developers.cloudflare.com/analytics/graphql-api/ and https://developers.cloudflare.com/analytics/graphql-api/limits/.
- D1 GraphQL analytics expose rows read/written, but adaptive analytics records only requests that successfully reach SQL execution; requests failing before SQL execution are not represented. Per-query Workers Binding API row counts are precise for those queries, but do not independently prove complete account-wide coverage. See https://developers.cloudflare.com/d1/observability/metrics-analytics/.
- Durable Objects expose several GraphQL datasets, including invocation, periodic, storage, and subrequest datasets. Their existence does not by itself prove that all billable dimensions are fully represented in one exact, unsampled account-wide counter. WebSocket request/message representation also varies by lifecycle and hibernation. See https://developers.cloudflare.com/durable-objects/observability/metrics-and-analytics/.
- Cloudflare's Billable Usage API is a useful reconciliation source across usage-based products, but its published update cadence is daily, not ten-minute real-time. It cannot satisfy this gate's freshness requirement. See https://blog.cloudflare.com/billable-usage-api/.
- GitHub's billing usage reports are date/product-oriented, while the workflow usage endpoint reports a specific workflow's current billing-cycle minutes and applies to private repositories using GitHub-hosted runners. That is not an independently complete, ten-minute account-wide meter for every Actions workload. See https://docs.github.com/en/rest/billing/usage and https://docs.github.com/en/rest/actions/workflows.
- Free-plan limits are metered across different periods and dimensions (for example, Workers requests and D1/DO daily limits, and other monthly dimensions). A single generic percentage is not valid unless the collector preserves each meter's exact unit, period, reset boundary, account scope, and authoritative limit. See https://developers.cloudflare.com/workers/platform/pricing/ and https://developers.cloudflare.com/durable-objects/platform/pricing/.

Therefore, do not implement a collector that converts GraphQL analytics, a recent poll timestamp, partial local counters, or daily billable-usage data into a ten-minute enforcement snapshot. Those sources may be retained for observability and later reconciliation only. Unless Cloudflare exposes a documented exact near-real-time enforcement meter for every required dimension, the safe decision is BLOCKED; no secret/variable configuration or workflow activation can compensate for missing authoritative telemetry.

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

The observation record helper in `scripts/distributed_loop_budget_observation.py` is not a live provider collector. It recognizes Workers, D1, Durable Objects, and GitHub Actions, but it does not create enforcement evidence. It normalizes measured values for reporting only and forcibly emits:

- `enforcement_eligible=false`
- `limit_verified=false`
- `limit=null` and `limit_evidence_id=null`

Caller-supplied limit values and authority flags are discarded. An `exact` measurement describes measurement quality only; it does not prove that the vendor quota or billing limit is authoritative. Observation records must never be passed as enforcement snapshots. The gate now rejects missing or unverified enforcement evidence, unsigned/self-asserted authority, mismatched collector/account identity, incomplete or sampled coverage, and stale watermarks.

No live Workers/D1/Durable Objects/GitHub usage collector, signed budget endpoint, provider credentials, deployment, or secret configuration is added here. The 30-minute loop remains blocked until independently verified enforcement evidence is available.
