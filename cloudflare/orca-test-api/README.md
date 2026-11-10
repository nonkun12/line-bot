# ORCA D1 atomic claim API (source-only proposal)

This directory is the source-controlled successor for the separately deployed
`orca-test-api` Worker. It is intentionally **not deployed** by this PR.

## Migration

Review `migrations/0002_atomic_claims_and_outbox.sql` against the live D1
schema before applying it. It adds optional LINE `user_id`, lease fields,
attempt count, and a durable notification outbox. Do not run the migration
until the live schema and migration history are confirmed.

## API

All routes require `Authorization: Bearer <API_TOKEN>`.

- `POST /tasks/:id/claim` atomically changes `queued` tasks (or expired `running` leases) to `running`,
  returns a random claim token and bounded lease expiry (60–1,800 seconds).
- `POST /tasks/:id/complete` requires the claim token and a terminal state
  (`pass`, `fail`, or `blocked`). A D1 batch inserts a notification intent
  and consumes the lease in one transaction. A stale, expired, or replayed token is rejected. The completion batch first
  consumes the lease, then inserts the outbox row only for that successful
  terminal transition, and finally clears the token.
- `GET /tasks` and `GET /tasks/:id` deliberately omit `user_id`,
  `lease_token`, and lease internals.
- Existing POST/GET/PUT routes remain for compatibility with the test MVP.
  New workers must use claim/complete. The legacy PUT route is not a secure
  substitute for lease-based execution.

## LINE notification

The scheduled handler uses a five-minute dispatch lease to prevent concurrent
senders from claiming the same outbox row, retries due entries with backoff,
and uses `LINE_CHANNEL_ACCESS_TOKEN` only in the Worker runtime. It never returns
credentials or recipient IDs in API responses. The existing LINE intake code
must separately be updated to submit `event.source.user_id`; until that
change is reviewed and deployed, tasks without a user ID receive no push
notification.

## Required safeguards before deployment

1. Confirm the actual production/test D1 schema and apply the migration once.
2. Configure `API_TOKEN` and `LINE_CHANNEL_ACCESS_TOKEN` as Worker secrets.
3. Update LINE intake to persist the verified event source user ID, without
   logging it; do not change the webhook URL.
4. Update the CPU worker to call `/claim` and `/complete` with the lease token.
5. Add integration tests against a disposable D1 database, including concurrent
   claims, stale-token completion, duplicate completion, and notification retry.
6. Review the retry/dead-letter policy and LINE push-message limits. Delivery
   is at-least-once: if LINE accepts a push but the network response is lost,
   a later retry may produce a duplicate notification.

The `wrangler.toml.example` file is a template only; it contains a placeholder
D1 ID and must not be deployed as-is. No deployed Worker, D1 database, secret,
Render service, LINE webhook, or workflow schedule is changed by this source-only proposal. Free GitHub runner
and Cloudflare quotas still apply; scheduling is best-effort.
