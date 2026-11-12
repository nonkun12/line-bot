# ORCA D1 atomic claim API (source-only proposal)

This directory is the source-controlled successor for the separately deployed
`orca-test-api` Worker. It is intentionally **not deployed** by this PR.

## Migrations

Review migrations:
- `0002_atomic_claims_and_outbox.sql`
- `0003_task_bound_approvals.sql`
- `0004_append_only_approval_nonce_history.sql`
- `0005_global_hold.sql`
- `0006_typed_task_execution.sql`

Review them against the live D1 schema before applying them in order. Migration 0002 adds verified LINE user ID storage,
lease fields, attempt count, and a durable notification outbox. Migration 0003
adds the current task approval record. Migration 0004 adds the append-only
nonce replay ledger and backfills the currently stored approval nonce. Migration
0005 creates `system_controls` with `global_hold=on`; it must remain engaged
until an operator explicitly authorizes a controlled rollout. Migration 0006
adds constrained `task_type` (`app_development` or `distributed_loop`) and
`max_tasks` (1–4), backfilling existing tasks and approvals as
`app_development` with `max_tasks=1`. Do not apply any migration until the live
schema and migration history are confirmed. Migrations 0002 and 0006 use
ALTER TABLE and are not safe to re-run blindly.

## API

All routes require `Authorization: Bearer <API_TOKEN>`.

- `POST /tasks/:id/approve` verifies an HMAC-SHA256 signature over protocol
  version, task ID, exact request SHA-256, verified LINE user ID, issue time,
  and one-hour expiry. App-development approvals retain protocol v1 for
  compatibility. Distributed-loop approvals use protocol v2, which also signs
  the exact task type and max-task bound. The API checks owner, type, bound,
  and request hash against D1 before storing a one-use approval.
- `GET /tasks` exposes only a boolean `approved` field for unexpired
  approvals; it does not expose the submitter ID, signature, or approval
  internals. With `approved=true`, it returns the oldest eligible tasks first.
- `POST /tasks/:id/claim` requires an unexpired approval and atomically
  consumes it while changing a queued task (or expired running lease) to
  running. It returns a random claim token and bounded lease expiry
  (60–1,800 seconds). If the lease expires before completion, a new LINE
  approval is required. The generic CPU worker and claim endpoint currently
  accept only `app_development`; `distributed_loop` claims return 409 until
  a dedicated bounded executor is implemented and reviewed.
- `GET /tasks?approved=true` defaults to `task_type=app_development`, so
  existing pollers cannot see or starve on distributed-loop tasks. A future
  dedicated executor may explicitly request `task_type=distributed_loop`; listing
  does not grant claim permission.
- `POST /tasks/:id/complete` requires the claim token and a terminal state
  (`pass`, `fail`, or `blocked`). A D1 batch commits the terminal transition,
  notification outbox intent, and lease cleanup together.
- `GET /tasks/:id` deliberately omits LINE user ID, lease token, and approval
  internals.
- `GET /tasks/:id/status` reads `X-ORCA-Task-Owner: <verified-line-user-id>` from a request header and returns only task ID,
  status, and timestamps when the supplied verified LINE user ID matches the
  task owner. Missing tasks and owner mismatches both return HTTP 404. The
  LINE bot exposes this as `タスク状態:<task_id>`; it is a read-only lookup.
- Legacy `PUT /tasks/:id` status changes return HTTP 410 to prevent bypassing
  the claim-token protocol.


### Approval nonce replay protection

Every accepted approval nonce is inserted into `task_approval_nonces`, whose
primary key permanently rejects reuse. The nonce insert and current-approval
upsert run in one D1 batch. A newer signed approval may replace an unconsumed
approval; an older or equal-issued-at approval cannot roll the current record
back. A fresh nonce is required to reauthorize after an expired running lease.
A stale but previously unused nonce is retained in the ledger and cannot be
retried.

Migration 0004 can backfill only the nonce still present in
`task_approvals`. Nonces overwritten before migration 0004 cannot be
reconstructed; treat the pre-migration replay window as a residual risk and
keep the API/worker disabled until the migration is applied and rollout
checks pass. Do not infer historical nonce coverage from the backfilled row.

## LINE notification

The scheduled handler uses a five-minute dispatch lease to prevent concurrent
senders from claiming the same outbox row, processes at most 10 rows per
invocation, retries with backoff, and uses `LINE_CHANNEL_ACCESS_TOKEN` only
inside the Worker runtime. Delivery is at-least-once: if LINE accepts a push
but the response is lost, a later retry may produce a duplicate notification.
The existing LINE intake must persist the verified event source user ID for
task-specific notifications.

## Required safeguards before deployment

1. Confirm the actual D1 schema and migration history; reconcile and apply
   migrations 0002, 0003, and 0004 once, in order.
2. Configure Worker secrets `API_TOKEN`, `LINE_CHANNEL_ACCESS_TOKEN`, and
   `ORCA_TASK_APPROVAL_HMAC_KEY`.
3. Configure the same high-entropy `ORCA_TASK_APPROVAL_HMAC_KEY` in Render.
   Do not reuse the API bearer token as the HMAC key. The task owner is the
   only permitted approver; the API verifies the event user ID against the
   stored task owner, so no separate allowlist is needed.
4. Update LINE intake to persist the verified event source user ID and support
   `タスク承認:<task_id>`, without logging identity or signatures. Do not
   change the webhook URL.
5. Use the CPU worker that polls only approved tasks and calls claim/complete
   with the lease token.
6. Add integration tests against a disposable D1 database for signed approval,
   owner mismatch, expiry, one-use consumption, concurrent claims, stale-token
   completion, duplicate completion, and notification retry.
7. Review the retry/dead-letter policy and LINE push-message limits.
8. Run the isolated local D1 integration suite in
   `tests/test_worker_d1_integration.py`. It starts Wrangler/workerd against a
   temporary local D1 store, seeds only the legacy baseline schema, applies
   migrations 0002–0006 locally, and tests real HTTP handlers, signed approval,
   owner binding, concurrent claims, stale tokens, and HOLD/outbox behavior.
   The CI job installs Wrangler and runs this suite with no Cloudflare account,
   remote binding, production database, or production secret.

The `wrangler.toml.example` file is a template only; it contains a placeholder
D1 ID and must not be deployed as-is. No deployed Worker, D1 database, secret,
Render service, LINE webhook, or workflow schedule is changed by this
source-only proposal. Free GitHub runner and Cloudflare quotas still apply;
scheduling is best-effort.

## Read-only live-D1 preflight (required before any migration)

Run these statements in the Cloudflare D1 console against **orca-test-ledger**
before planning a rollout. They are inspection-only; do not paste credentials
or task contents into a ticket or chat.

```sql
-- 1. Confirm the actual tasks columns and their defaults.
PRAGMA table_info(tasks);

-- 2. Inspect migration bookkeeping and the ORCA support tables, including nonce history.
SELECT type, name, sql
  FROM sqlite_master
 WHERE name IN ('d1_migrations', 'task_approvals', 'notification_outbox', 'task_approval_nonces')
    OR name LIKE 'idx_tasks_%'
 ORDER BY type, name;

-- 3. Check whether columns introduced by migrations 0002 and 0006 already exist.
-- Compare this result with PRAGMA table_info(tasks); do not infer from this query alone.
SELECT name
  FROM pragma_table_info('tasks')
 WHERE name IN ('user_id', 'lease_token', 'lease_until', 'attempt_count',
                'task_type', 'max_tasks')
 ORDER BY name;

-- 4. Inspect the approval metadata columns added by migration 0006.
PRAGMA table_info(task_approvals);

-- 5. Read-only referential-integrity check.
PRAGMA foreign_key_check;
```

Expected pre-migration baseline for the currently deployed intake is the
original `tasks` table (including `task_id`, `request_text`, `status`,
timestamps, and `source_event_id`), with none of the four 0002 columns or
the two 0006 columns, and without `task_approvals` or `notification_outbox`. Treat this as an
expectation to verify, not as proof of the live schema.

**Stop without applying anything** if a required table/column is missing,
one or more 0002 or 0006 columns already exist, any support table already exists
with an unexpected shape, the migration history is unclear, or
`foreign_key_check` returns rows. The repository currently has no 0001
baseline migration; the original intake schema was created separately, so
the Wrangler migration ledger alone may not describe the full database
history. Capture a protected D1 export/snapshot through the approved
Cloudflare process before any write migration.

Only after the schema, migration history, backup, and exact SQL diff have
been reviewed should an operator apply 0002, 0003, 0004, and 0005 exactly once.
Do not use `CREATE TABLE IF NOT EXISTS` as evidence that an existing table
has the expected schema, and do not rerun 0002 to recover from a partial
failure. If the observed state is mixed or partial, prepare a separately
reviewed reconciliation migration instead. This PR does not execute any
preflight query or migration against the live database.
## Controlled rollout order (no automatic activation)

Keep all four related PRs in Draft until the review and deployment prerequisites
are complete. Merging is not authorized by this proposal.

1. **D1/API first — PR #1333.** Verify the live schema using the read-only
   preflight above, create and protect a backup, reconcile any differences,
   then apply migrations 0002, 0003, 0004, and 0005 exactly once. Review and
   deploy this Worker source separately; configure and verify its required
   secrets. Keep initial Global HOLD engaged.
2. **LINE identity and approval — PR #1334.** Review and deploy the Render bot
   code only after the API approval endpoint and HMAC key are ready. Keep the
   existing LINE webhook URL unchanged. Confirm that a test task stores the
   verified LINE user ID without exposing it in normal task reads.
3. **CPU worker — PR #1332.** Before merging, create the
   `orca-task-execution` GitHub Environment, configure at least one required
   reviewer, add the non-empty sentinel secret, and configure the API token.
   Verify the actual environment protection settings in GitHub; a sentinel
   secret alone is not a human approval gate. Merging this PR activates its
   15-minute schedule, so do not merge it early.
4. **End-to-end verification.** With Global HOLD still engaged, verify the
   worker remains idle. Then perform a separately approved controlled test:
   submit a non-sensitive `アプリ開発:` task, approve it from the same LINE
   account, and verify one claim, isolated test result, review-only PR, D1
   terminal state, and LINE notification. Confirm replay, wrong-user,
   expired-approval, stale-token, and duplicate-claim cases are rejected.
5. **Legacy-loop cutover — PR #1331 only after replacement readiness.** This PR
   disables nine existing autonomous workflows. It must remain Draft and
   unmerged while those loops are still needed. Merge it only after the new
   path has passed end-to-end verification and the operator explicitly accepts
   the legacy-loop shutdown/cutover window. If uninterrupted legacy loops are
   required, #1331 must be redesigned to route them safely rather than disable
   them.

At every stage, stop on missing evidence. Do not enable the CPU worker until
all earlier stages are independently verified. No merge, deploy, migration,
secret update, or webhook change is performed by this README update.

## Global HOLD (migration 0005)

Migration `0005_global_hold.sql` creates the D1 `system_controls` table and inserts
`global_hold=on` by default. Apply it only after reviewing the existing D1 schema
and taking the normal migration backup. Until the migration is applied and a human
explicitly changes that row to the exact value `off`, intake, approval, claim,
polling, and LINE outbox dispatch remain blocked. Missing or unreadable state is
also treated as HOLD.

Task completion may still record terminal evidence while HOLD is active, but it
does not enqueue a LINE notification. Outbox dispatch checks HOLD before claiming
and again immediately before the LINE request. A D1 state change cannot be made
atomic with an already-starting external LINE API request; this boundary is
documented rather than represented as cross-system atomicity.

No production D1 migration or Worker deployment is performed by this PR.


## Serialized GitHub write broker (Draft implementation)

The Worker exports `OrcaWriteBroker` as a SQLite-backed Durable Object. The
`ORCA_WRITE_BROKER` binding and its `v1-orca-write-broker` migration are
required; if the binding or stored state is missing, the broker reports
Global HOLD=ON.

The Durable Object serializes its own requests with
`blockConcurrencyWhile`. Its HOLD state is authoritative; the D1
`system_controls` row is a compatibility mirror. HOLD transitions are
ordered safely:
- ON is persisted in the broker before D1 is updated.
- OFF updates D1 first and releases the broker last.
- The Worker requires both the normal API bearer and the separate
  `ORCA_HOLD_OPERATOR_TOKEN` header to change HOLD. Releasing HOLD also
  requires an operator ID and a reason. Keep this operator secret out of
  GitHub Actions and task-worker environments.

### Implemented operation: review Issue creation

`POST /internal/github/issues` accepts a bounded review Issue request only
when the D1 task is currently claimed, its lease token is valid, the consumed
approval matches the task fingerprint, and the task is an
`app_development` task. The broker fixes the repository from
`GITHUB_REPOSITORY` and fixes the label to `orca-task-review`; clients
cannot choose an API URL, method, repository, or label.

The broker mints a short-lived GitHub App installation token internally.
Configure these Worker-only secrets/vars before using this operation:
`GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`,
`GITHUB_APP_INSTALLATION_ID`, and `GITHUB_REPOSITORY=nonkun12/line-bot`.
The GitHub App should be installed only on this repository with **Issues:
write** permission for this first operation. No App, installation, token, or
secret has been created or configured by this PR.

Every request requires an idempotency key. Completed results are replayed
without another GitHub call. An in-flight, timed-out, or otherwise uncertain
outcome is not retried automatically; it returns a conflict/manual-reconcile
result to avoid duplicate Issues.

### Explicit limitations of this phase

This is the first broker slice, not the complete autonomous write migration.
Only review Issue creation is brokered. Branch pushes, PR creation/updates,
autonomous-state writes, Google Sheets, Render, and LINE notifications are
not yet routed through this Durable Object. Existing legacy workflows still
have direct write paths, and D1 task/LINE side effects are not atomic with
GitHub. Therefore this implementation does **not** yet justify enabling
autonomous execution or claiming that Global HOLD drains every external side
effect. Keep all replacement workflows disabled/held until each write path
has been migrated and independently tested.

If a GitHub request times out or returns an ambiguous 5xx/408/429, the
operation is recorded as `uncertain` and the broker enters `DRAINING`.
New writes are blocked, and a HOLD ON request is **not acknowledged** until
the uncertain operation is manually reconciled. Use the separately
authenticated `POST /control/global-hold/reconcile` route only after checking
GitHub for the embedded task/idempotency marker. Then explicitly acknowledge
HOLD ON or deliberately release HOLD. The ledger inspection limit is 2,001
records; reaching it fails closed and requires manual maintenance.

Both HOLD ON and HOLD OFF require the separate operator credential, an
operator ID audit label, and a reason. The operator ID is supplied by the
authenticated caller and is not an independently verified GitHub identity.

The broker allows at most one review Issue operation per task, even if a
caller supplies a different idempotency key on a retry. A new Issue requires a
new independently approved task.
