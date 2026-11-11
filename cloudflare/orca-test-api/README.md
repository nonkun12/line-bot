# ORCA D1 atomic claim API (source-only proposal)

This directory is the source-controlled successor for the separately deployed
`orca-test-api` Worker. It is intentionally **not deployed** by this PR.

## Migrations

Review migrations `0002_atomic_claims_and_outbox.sql`,
`0003_task_bound_approvals.sql`, and
`0004_append_only_approval_nonce_history.sql` against the live D1 schema before
applying them in order. Migration 0002 adds verified LINE user ID storage,
lease fields, attempt count, and a durable notification outbox. Migration 0003
adds the current task approval record. Migration 0004 adds the append-only
nonce replay ledger and backfills the currently stored approval nonce. Do not apply either migration until the live
schema and migration history are confirmed. Migration 0002 uses ALTER TABLE
and is not safe to re-run blindly.

## API

All routes require `Authorization: Bearer <API_TOKEN>`.

- `POST /tasks/:id/approve` verifies an HMAC-SHA256 signature over protocol
  version, task ID, exact request SHA-256, verified LINE user ID, issue time,
  and one-hour expiry. It confirms the LINE user ID matches the task's
  stored submitter identity and recomputes the request hash from D1 before
  storing a one-use approval.
- `GET /tasks` exposes only a boolean `approved` field for unexpired
  approvals; it does not expose the submitter ID, signature, or approval
  internals. With `approved=true`, it returns the oldest eligible tasks first.
- `POST /tasks/:id/claim` requires an unexpired approval and atomically
  consumes it while changing a queued task (or expired running lease) to
  running. It returns a random claim token and bounded lease expiry
  (60–1,800 seconds). If the lease expires before completion, a new LINE
  approval is required.
- `POST /tasks/:id/complete` requires the claim token and a terminal state
  (`pass`, `fail`, or `blocked`). A D1 batch commits the terminal transition,
  notification outbox intent, and lease cleanup together.
- `GET /tasks/:id` deliberately omits LINE user ID, lease token, and approval
  internals.
- `GET /tasks/:id/status?user_id=<verified-line-user-id>` returns only task ID,
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

-- 3. Check whether any of the columns introduced by migration 0002 already exist.
-- Compare this result with PRAGMA table_info(tasks); do not infer from this query alone.
SELECT name
  FROM pragma_table_info('tasks')
 WHERE name IN ('user_id', 'lease_token', 'lease_until', 'attempt_count')
 ORDER BY name;

-- 4. Read-only referential-integrity check.
PRAGMA foreign_key_check;
```

Expected pre-migration baseline for the currently deployed intake is the
original `tasks` table (including `task_id`, `request_text`, `status`,
timestamps, and `source_event_id`), with none of the four 0002 columns and
without `task_approvals` or `notification_outbox`. Treat this as an
expectation to verify, not as proof of the live schema.

**Stop without applying anything** if a required table/column is missing,
one or more 0002 columns already exist, any support table already exists
with an unexpected shape, the migration history is unclear, or
`foreign_key_check` returns rows. The repository currently has no 0001
baseline migration; the original intake schema was created separately, so
the Wrangler migration ledger alone may not describe the full database
history. Capture a protected D1 export/snapshot through the approved
Cloudflare process before any write migration.

Only after the schema, migration history, backup, and exact SQL diff have
been reviewed should an operator apply 0002, 0003, and 0004 exactly once.
Do not use `CREATE TABLE IF NOT EXISTS` as evidence that an existing table
has the expected schema, and do not rerun 0002 to recover from a partial
failure. If the observed state is mixed or partial, prepare a separately
reviewed reconciliation migration instead. This PR does not execute any
preflight query or migration against the live database.
## Controlled rollout order (no automatic activation)

Keep all four related PRs in Draft until the review and deployment prerequisites
are complete. Merging is not authorized by this proposal.

1. **Safety hold first — PR #1331.** Review and merge the fail-closed hold
   before enabling the new worker. This holds the identified existing
   autonomous execution entry points while the new path is prepared.
2. **D1/API second — PR #1333.** Verify the live schema using the read-only
   preflight above, create and protect a backup, reconcile any differences,
   then apply migrations 0002, 0003, and 0004 exactly once. Review and deploy this
   Worker source separately; configure and verify its required secrets.
3. **LINE identity and approval third — PR #1334.** Review and deploy the
   Render bot code only after the API approval endpoint and HMAC key are ready.
   Keep the existing LINE webhook URL unchanged. Confirm that a new test task
   stores the verified LINE user ID without exposing it in normal task reads.
4. **CPU worker last — PR #1332.** Before merging, create the
   `orca-task-execution` GitHub Environment, configure at least one required
   reviewer, add the non-empty sentinel secret, and configure the API token.
   Verify the actual environment protection settings in GitHub; a sentinel
   secret alone is not a human approval gate. Merging this PR activates its
   15-minute schedule, so do not merge it early.
5. **End-to-end test.** Submit a non-sensitive `アプリ開発:` test task, approve
   it from the same LINE account, verify one successful claim, isolated test
   result, review-only PR, D1 terminal state, and LINE notification. Confirm
   replay, wrong-user, expired-approval, and duplicate-claim cases are rejected.

At every stage, stop on missing evidence. Do not enable the CPU worker until
all earlier stages are independently verified. No merge, deploy, migration,
secret update, or webhook change is performed by this README update.