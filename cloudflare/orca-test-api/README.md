# ORCA D1 atomic claim API (source-only proposal)

This directory is the source-controlled successor for the separately deployed
`orca-test-api` Worker. It is intentionally **not deployed** by this PR.

## Migration

Review migrations `0002_atomic_claims_and_outbox.sql` and
`0003_task_bound_approvals.sql` against the live D1 schema before applying
both in order. Migration 0002 adds LINE `user_id`, lease fields, attempt count,
and a durable notification outbox. Migration 0003 adds the one-use approval
ledger. Do not apply either until the live schema and migration history are
confirmed.

## API

All routes require `Authorization: Bearer <API_TOKEN>`.

- `POST /tasks/:id/approve` verifies an HMAC-SHA256 signature over version,
  task ID, exact request SHA-256, allowlisted LINE user ID, issue time, and
  five-minute expiry. It recomputes the task hash from D1 before storing a
  one-use approval. The HMAC key and approver allowlist are separate Worker
  secrets/vars and must match the Render configuration.
- `GET /tasks` exposes only a boolean `approved` field for unexpired approvals;
  it does not expose the approver ID, signature, or approval internals.
- `POST /tasks/:id/claim` requires an unexpired approval and atomically consumes
  it while changing `queued` (or expired `running`) to `running`, returning a
  random claim token and bounded lease expiry (60–1,800 seconds). A task whose
  lease expires needs a fresh LINE approval.
- `POST /tasks/:id/complete` requires the claim token and a terminal state
  (`pass`, `fail`, or `blocked`). A D1 batch inserts a notification intent
  and consumes the lease in one transaction. A stale, expired, or replayed token is rejected. The completion batch first
  consumes the lease, then inserts the outbox row only for that successful
  terminal transition, and finally clears the token.
- `GET /tasks` and `GET /tasks/:id` deliberately omit `user_id`,
  `lease_token`, and lease internals.
- Existing POST/GET read routes remain compatible. Legacy PUT status changes
  return HTTP 410 so callers cannot bypass the claim-token lease protocol.
  The CPU worker must be upgraded to claim/complete before this API is deployed.

## LINE notification

The scheduled handler uses a five-minute dispatch lease to prevent concurrent
senders from claiming the same outbox row, processes at most 10 rows per invocation
to stay below the Workers free-plan subrequest ceiling, and retries due entries with backoff,
and uses `LINE_CHANNEL_ACCESS_TOKEN` only in the Worker runtime. It never returns
credentials or recipient IDs in API responses. The existing LINE intake code
must separately be updated to submit `event.source.user_id`; until that
change is reviewed and deployed, tasks without a user ID receive no push
notification.

## Required safeguards before deployment

1. Confirm the actual production/test D1 schema and apply the migration once.
2. Configure `API_TOKEN`, `LINE_CHANNEL_ACCESS_TOKEN`, and
   `ORCA_TASK_APPROVAL_HMAC_KEY` as Worker secrets; configure
   `ORCA_TASK_APPROVER_USER_IDS` as a tightly controlled Worker variable.
3. Configure the exact same high-entropy `ORCA_TASK_APPROVAL_HMAC_KEY` and
   identical minimal `ORCA_TASK_APPROVER_USER_IDS` allowlist in Render. Do not
   reuse the API bearer token as the HMAC key.
4. Update LINE intake to persist the verified event source user ID and support
   `タスク承認:<task_id>`, without logging identity or signatures; do not change
   the webhook URL.
5. Update the CPU worker to poll only approved tasks and call `/claim` and
   `/complete` with the lease token.
6. Add integration tests against a disposable D1 database, including signed
   approval verification, one-use consumption, concurrent claims, stale-token
   completion, duplicate completion, and notification retry.
7. Review the retry/dead-letter policy and LINE push-message limits. Delivery
   is at-least-once: if LINE accepts a push but the network response is lost,
   a later retry may produce a duplicate notification.

The `wrangler.toml.example` file is a template only; it contains a placeholder
D1 ID and must not be deployed as-is. No deployed Worker, D1 database, secret,
Render service, LINE webhook, or workflow schedule is changed by this source-only proposal. Free GitHub runner
and Cloudflare quotas still apply; scheduling is best-effort.
