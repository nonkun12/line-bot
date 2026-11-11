# ORCA D1 atomic claim API (source-only proposal)

This directory is the source-controlled successor for the separately deployed
`orca-test-api` Worker. It is intentionally **not deployed** by this PR.

## Migrations

Review migrations `0002_atomic_claims_and_outbox.sql` and
`0003_task_bound_approvals.sql` against the live D1 schema before applying
them in order. Migration 0002 adds verified LINE user ID storage, lease fields,
attempt count, and a durable notification outbox. Migration 0003 adds the
one-use task approval ledger. Do not apply either migration until the live
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
- Legacy `PUT /tasks/:id` status changes return HTTP 410 to prevent bypassing
  the claim-token protocol.

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
   migrations 0002 and 0003 once, in order.
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
