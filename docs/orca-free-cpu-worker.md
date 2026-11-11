# ORCA free CPU task worker

This is a public-repository GitHub Actions worker. It uses the free GitHub-hosted
CPU runner and a local Ollama model (`qwen2.5-coder:1.5b`). It does not use
Groq, a paid inference API, a Mac, or a paid VM.

## What it does

1. Every 15 minutes, a read-only job checks the Cloudflare D1 task API for
   the oldest queued `アプリ開発:` task that has a valid, unexpired,
   task-bound LINE approval. Unapproved tasks are not sent to the execution job.
2. A verified LINE account on the explicit approver allowlist sends
   `タスク承認:<task_id>`. The Render bot fetches the exact queued task,
   hashes the full request text, and signs a versioned HMAC payload binding
   task ID, request hash, LINE user ID, issue time, and five-minute expiry.
3. The Cloudflare API verifies the HMAC, checks the LINE user ID against its
   own allowlist, recomputes the live task hash, and stores one approval record.
   The atomic claim consumes that approval in the same D1 transaction that
   acquires the task lease. Replays, expired approvals, changed task text, and
   unapproved claims are rejected.
4. The execution job also waits at the GitHub Environment named
   `orca-task-execution` when required reviewers are configured. This is an
   additional gate; it is not a substitute for the signed, task-bound LINE
   approval. A non-empty sentinel secret only detects incomplete setup.
5. The worker claims the task, runs local CPU inference, validates a patch
   containing only new app files, runs the generated app's pytest suite in a
   network-disabled container that receives only a read-only copy of the new
   app files (not the repository workspace), and opens a review-only PR.
6. It updates D1 only with a lease-bound terminal result. It never merges or
   deploys. A consumed approval is one-use; if a lease expires before a
   successful completion, the task requires a fresh LINE approval.

## Atomic API dependency (PR #1333) and LINE approval dependency (PR #1334)

The worker uses the lease and signed-approval API proposed in
[PR #1333](https://github.com/nonkun12/line-bot/pull/1333):

- `POST /tasks/:id/approve` accepts only an HMAC-signed approval from an
  allowlisted LINE user and binds it to the current request-text SHA-256.
- `GET /tasks` exposes only a boolean `approved` field for unexpired approvals.
- `POST /tasks/:id/claim` requires and consumes the approval atomically with
  the task lease. It returns 403/409 without a valid unconsumed approval.
- `POST /tasks/:id/complete` requires the lease token and a terminal state.
- Legacy `PUT /tasks/:id` status changes remain disabled.

[PR #1334](https://github.com/nonkun12/line-bot/pull/1334) adds the verified
LINE source user ID to task intake and the explicit `タスク承認:<task_id>`
command. Both PRs are source-only and are not merged or deployed. The current
deployed Worker does not yet expose these endpoints. Do not enable or dispatch
the worker against the current API until both PRs have been reviewed, migrations
0002 and 0003 have been reconciled with the live D1 schema and safely applied,
and the Worker is deployed through a separately approved rollout.

## Current boundaries and known gaps

- Only one workflow run can poll/execute at a time (`concurrency` group).
  This serializes runs of this workflow only. The D1 lease in PR #1333 is the
  cross-caller atomic claim mechanism; it is not active until that API revision
  is deployed and the worker is enabled against it.
- If a task branch already has an open PR, the worker reuses its URL instead of creating a duplicate. If PR creation succeeds but final D1 completion fails, it leaves the task running until lease expiry and emits a reconciliation warning rather than marking a reviewable PR as failed.\n- The deployed intake still does not retain LINE `user_id`; task-specific push
  notifications remain unavailable until a separately reviewed intake update
  stores the verified event source user ID.
- The CPU model is small. It may fail to produce a valid patch; failures are
  recorded and do not trigger a merge or deployment.
- GitHub-hosted runner availability and free quotas are subject to GitHub's
  current plan and usage limits. The workflow is scheduled, not guaranteed to
  start at an exact minute.
- The worker only processes `アプリ開発:` tasks and creates a new self-contained Python app under apps/<slug>/;
  it cannot change existing applications or line-bot source files. Every app must
  include a tests/test_*.py file. Generated tests run in a container with no network
  and no GitHub/D1 credentials. The test container has a read-only filesystem apart from a temporary `/tmp`, runs as an unprivileged user, and mounts only the generated app files.
- The worker is not enabled until the API dependency is deployed through an
  approved rollout and the required repository secret and protected environment
  are configured. No secret, webhook, Render service, Cloudflare
  Worker, or deployment is modified by this PR.## Required one-time configuration before any rollout

These settings are manual and are not changed by this PR. Never put secrets in
chat, source control, workflow summaries, or task text.

1. Add repository Actions secret `ORCA_TASK_API_TOKEN` for the existing API.
2. Configure the same randomly generated, high-entropy (at least 32-byte)
   `ORCA_TASK_APPROVAL_HMAC_KEY` as a Render environment secret and a
   Cloudflare Worker secret. Do not reuse `API_TOKEN`.
3. Configure `ORCA_TASK_APPROVER_USER_IDS` on both Render and Cloudflare with
   the exact verified LINE user IDs authorized to approve tasks. Keep the
   allowlists identical and minimal. Do not put these IDs in logs.
4. Configure the Cloudflare Worker secrets `API_TOKEN`,
   `LINE_CHANNEL_ACCESS_TOKEN`, and `ORCA_TASK_APPROVAL_HMAC_KEY`.
5. Create GitHub Environment `orca-task-execution`, configure required
   reviewers, and add non-empty sentinel `ORCA_TASK_APPROVAL_GATE`.
   Required reviewers are an additional gate, not task-bound approval.
6. Ensure Actions are allowed to create branches and pull requests. The
   workflow requests only `contents: write` and `pull-requests: write`
   for its execution job.

The LINE approval expires after five minutes and is consumed on the first
successful claim. If a worker lease expires, a fresh explicit LINE approval
is required. Until the secrets and allowlists are configured on both sides,
approval and execution fail closed.

## Atomic API dependency (PR #1333) and LINE approval dependency (PR #1334)

The worker uses the lease and signed-approval API proposed in
[PR #1333](https://github.com/nonkun12/line-bot/pull/1333):

- `POST /tasks/:id/approve` accepts only an HMAC-signed approval from an
  allowlisted LINE user and binds it to the current request-text SHA-256.
- `GET /tasks` exposes only a boolean `approved` field for unexpired approvals.
- `POST /tasks/:id/claim` requires and consumes the approval atomically with
  the task lease. It returns 403/409 without a valid unconsumed approval.
- `POST /tasks/:id/complete` requires the lease token and a terminal state.
- Legacy `PUT /tasks/:id` status changes remain disabled.

[PR #1334](https://github.com/nonkun12/line-bot/pull/1334) adds the verified
LINE source user ID to task intake and the explicit `タスク承認:<task_id>`
command. Both PRs are source-only and are not merged or deployed. The current
deployed Worker does not yet expose these endpoints. Do not enable or dispatch
the worker against the current API until both PRs have been reviewed, migrations
0002 and 0003 have been reconciled with the live D1 schema and safely applied,
and the Worker is deployed through a separately approved rollout.

## Current boundaries and known gaps

- Only one workflow run can poll/execute at a time (`concurrency` group).
  This serializes runs of this workflow only. The D1 lease in PR #1333 is the
  cross-caller atomic claim mechanism; it is not active until that API revision
  is deployed and the worker is enabled against it.
- If a task branch already has an open PR, the worker reuses its URL instead of creating a duplicate. If PR creation succeeds but final D1 completion fails, it leaves the task running until lease expiry and emits a reconciliation warning rather than marking a reviewable PR as failed.\n- The deployed intake still does not retain LINE `user_id`; task-specific push
  notifications remain unavailable until a separately reviewed intake update
  stores the verified event source user ID.
- The CPU model is small. It may fail to produce a valid patch; failures are
  recorded and do not trigger a merge or deployment.
- GitHub-hosted runner availability and free quotas are subject to GitHub's
  current plan and usage limits. The workflow is scheduled, not guaranteed to
  start at an exact minute.
- The worker only processes `アプリ開発:` tasks and creates a new self-contained Python app under apps/<slug>/;
  it cannot change existing applications or line-bot source files. Every app must
  include a tests/test_*.py file. Generated tests run in a container with no network
  and no GitHub/D1 credentials. The test container has a read-only filesystem apart from a temporary `/tmp`, runs as an unprivileged user, and mounts only the generated app files.
- The worker is not enabled until the API dependency is deployed through an
  approved rollout and the required repository secret and protected environment
  are configured. No secret, webhook, Render service, Cloudflare
  Worker, or deployment is modified by this PR.
