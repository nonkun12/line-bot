# ORCA free CPU task worker

This is a public-repository GitHub Actions worker. It uses the free GitHub-hosted
CPU runner and a local Ollama model (`qwen2.5-coder:1.5b`). It does not use
Groq, a paid inference API, a Mac, or a paid VM.

## What it does

1. Every 15 minutes, a read-only job checks the existing Cloudflare D1 task API
   for one queued task whose request starts with the explicit `アプリ開発:` prefix.
2. If a task exists, the execution job waits at the GitHub Environment named
   `orca-task-execution`.
3. After an authorized reviewer approves that environment deployment, the worker
   claims the task, runs local CPU inference, validates a patch containing only new app files,
   runs the generated app's pytest suite in a network-disabled container that receives only a read-only copy of the new app files (not the repository workspace), and opens a review-only PR.
4. It updates the D1 task status to `pass` or `fail`. It never merges or deploys.

## Required one-time repository configuration

These are manual GitHub settings; this PR does not create secrets or change
repository/environment permissions.

1. Add repository Actions secret `ORCA_TASK_API_TOKEN` with the existing
   Cloudflare API token already held outside GitHub. Do not paste it into chat.
2. Create the GitHub Environment `orca-task-execution`.
3. Configure **required reviewers** for that environment (the task must wait
   for human approval on every execution).
4. Add environment secret `ORCA_TASK_APPROVAL_GATE` with any non-empty
   sentinel value. The worker fails closed if this secret is absent.
5. Ensure Actions are allowed to create branches and pull requests. The workflow
   requests only `contents: write` and `pull-requests: write` for its job.

The environment reviewer rule is the actual per-run approval gate. The sentinel
secret only detects incomplete setup; it is not itself an authentication token.
Do not run this workflow until required reviewers have been configured.

## Atomic API dependency (separate PR #1333)

The worker now uses the lease-based API proposed in
[PR #1333](https://github.com/nonkun12/line-bot/pull/1333):

- It claims a task with `POST /tasks/:id/claim` and a 30-minute lease.
- It verifies the claimed request text before inference.
- It completes with `POST /tasks/:id/complete`, the claim token, and a terminal state.
- It does not use legacy `PUT /tasks/:id` status updates.

PR #1333 is source-only and is not merged or deployed. The existing deployed
Worker does not yet expose these endpoints. Do not enable or dispatch this
worker against the current API until the API PR has been reviewed, its D1
migration has been safely applied, and the Worker is deployed through an
explicitly approved rollout. The same rollout must separately add the LINE
user ID at task intake and configure the LINE notification secret.

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
