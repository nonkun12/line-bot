# ORCA free CPU task worker

This is a public-repository GitHub Actions worker. It uses a GitHub-hosted CPU
runner and a local Ollama model (`qwen2.5-coder:1.5b`). It does not use Groq,
a paid inference API, a Mac, or a paid VM. GitHub free quotas and runner
availability still apply; zero-cost or exact-time execution is not guaranteed.

## What it does

1. Every 15 minutes, a read-only job asks D1 for the oldest claimable (queued or expired-lease)
   `アプリ開発:` task with a valid, unexpired task-bound approval.
   Unapproved tasks are not passed to the execution job. Only the opaque
   task ID crosses the Actions job boundary; the protected execution job
   reloads the request from the authenticated API, so raw task text is not
   embedded in workflow outputs.
2. The same verified LINE account that submitted the task sends
   `タスク承認:<task_id>`. The Render bot fetches the exact queued task,
   hashes the full request text, and signs a versioned HMAC payload binding
   task ID, request hash, LINE user ID, issue time, and one-hour expiry.
3. The Cloudflare API verifies the HMAC, confirms that the LINE user ID is
   the task's stored submitter identity, recomputes the live task hash, and
   stores a one-use approval record. The atomic claim consumes that approval
   in the same D1 transaction that acquires the task lease. Replays, expired
   approvals, changed task text, and unapproved claims are rejected.
4. The execution job also waits at the GitHub Environment
   `orca-task-execution` when required reviewers are configured. This is an
   additional gate, not a substitute for signed task-bound LINE approval.
5. The worker runs local CPU inference, validates a patch containing only new
   app files, tests those files in a network-disabled read-only container, and
   opens a review-only PR. It never merges or deploys.
6. A consumed approval is one-use. If the worker lease expires before
   completion, a fresh LINE approval is required.

## Required configuration before rollout

These settings are manual and are not changed by this PR. Never put secrets in
chat, source control, workflow summaries, or task text.

1. Add repository Actions secret `ORCA_TASK_API_TOKEN` for the D1 API.
2. Generate a high-entropy secret (at least 32 random bytes) and configure the
   same value as `ORCA_TASK_APPROVAL_HMAC_KEY` in Render and as a Cloudflare
   Worker secret. Do not reuse `API_TOKEN`.
3. Configure Cloudflare Worker secrets `API_TOKEN` and
   `LINE_CHANNEL_ACCESS_TOKEN`.
4. Create GitHub Environment `orca-task-execution`, configure required
   reviewers, and add non-empty sentinel `ORCA_TASK_APPROVAL_GATE`.
   The sentinel only detects incomplete setup; it is not an approval token.
5. Ensure Actions are allowed to create branches and pull requests. The
   execution job requests only `contents: write` and `pull-requests: write`.

The LINE approval expires after one hour and is consumed on the first
successful claim. The task owner is the only permitted approver, so no separate
LINE-user allowlist is required. Until the shared HMAC secret and required
workflow protections are configured, execution remains fail-closed.

## Dependencies and rollout order

- [PR #1333](https://github.com/nonkun12/line-bot/pull/1333) adds the D1
  approval ledger, HMAC verification, approved-only polling field, atomic
  claim/complete endpoints, and notification outbox.
- [PR #1334](https://github.com/nonkun12/line-bot/pull/1334) adds verified LINE
  user ID persistence and the `タスク承認:<task_id>` command.
- This PR (#1332) polls only tasks with an unexpired approval and uses the
  claim-token protocol.

All three PRs are source-only and remain unmerged. The deployed Worker does
not yet expose the proposed endpoints. Do not enable or dispatch this worker
against the current API until the PRs have been reviewed, migrations 0002 and
0003 have been reconciled with the live D1 schema and applied once, the Worker
source has been deployed through a separately approved rollout, and required
secrets/protections have been configured.

## Safety boundaries and known gaps

- Only one workflow run can poll/execute at a time. The D1 lease is the
  cross-caller atomic claim mechanism, but it is inactive until the API rollout.
- Repository context collection skips sensitive path names and excludes an entire file when its first 5,000 characters match common credential patterns (secret assignments, private-key headers, and common provider token formats). This is a conservative heuristic, not a complete DLP scanner; it cannot guarantee detection of every secret or encoded value. Keep credentials out of tracked source and documentation, and review model context handling before rollout.
- The generated patch can add at most three new files under one
  `apps/<slug>/` directory, must include a `tests/test_*.py` file, uses only
  Python standard library code, and cannot modify existing files or workflows.
- Tests run in a network-disabled container with only a read-only copy of the
  generated app files, no repository workspace, and no GitHub/D1 credentials.
- If a task PR is created but final D1 completion fails, the task remains
  running until lease expiry. After fresh LINE approval, a retry checks the
  existing PR's open state, exact head SHA, deterministic branch, `main` base,
  task ID, and request hash; it fetches that exact commit, verifies that the
  diff contains only the allowed new-app files, and reruns the isolated tests
  before reconciling D1 completion. A changed head, mismatched PR, unsafe diff,
  or failed test is blocked and reported; it is never treated as a successful
  result.
- LINE notification delivery is at-least-once; duplicate pushes are possible
  if LINE accepts a message but the response is lost.
- No secrets, webhook URL, Render service, Cloudflare Worker, D1 database,
  workflow schedule, or deployment are changed by this source-only PR.
## Activation warning

This workflow declares a 15-minute schedule. **Merging this PR activates that
schedule immediately.** Keep it in Draft until PRs #1331, #1333, and #1334
have been reviewed and their required rollout steps are complete, the live D1
migrations and Worker endpoints are verified, the Render HMAC signer is
configured, and the GitHub Environment has an actual required reviewer.
A non-empty sentinel secret does not enforce human approval by itself.

Do not manually dispatch this workflow as an integration test before those
conditions are met. Use a disposable D1 database for pre-deployment contract
tests; use a separately approved, non-sensitive end-to-end task only after
the rollout checklist in the #1333 README is complete.