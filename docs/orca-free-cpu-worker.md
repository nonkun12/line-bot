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

## Current boundaries and known gaps

- Only one workflow run can poll/execute at a time (`concurrency` group).
  This reduces duplicate claims, but the current D1 API does not expose a
  documented atomic lease/claim endpoint. The worker verifies the `queued → running`
  transition before inference. A future API revision should add an atomic,
  lease-based claim before increasing worker concurrency.
- If a task branch already has an open PR, the worker reuses its URL instead of creating a duplicate. If PR creation succeeds but the final D1 status update fails, it leaves the task `running` and emits a reconciliation warning rather than marking a reviewable PR as failed. This requires manual reconciliation; it is not an automatic lease/retry mechanism.\n- The task intake schema currently stores `task_id`, `request_text`, and
  `source_event_id`; it does not retain the LINE `user_id`. Therefore this
  first version cannot send a task-specific LINE completion message. The PR URL
  appears in the Actions log and the D1 status is updated.
- The CPU model is small. It may fail to produce a valid patch; failures are
  recorded and do not trigger a merge or deployment.
- GitHub-hosted runner availability and free quotas are subject to GitHub's
  current plan and usage limits. The workflow is scheduled, not guaranteed to
  start at an exact minute.
- The worker only processes `アプリ開発:` tasks and creates a new self-contained Python app under apps/<slug>/;
  it cannot change existing applications or line-bot source files. Every app must
  include a tests/test_*.py file. Generated tests run in a container with no network
  and no GitHub/D1 credentials. The test container has a read-only filesystem apart from a temporary `/tmp`, runs as an unprivileged user, and mounts only the generated app files.
- The worker is not enabled until the required repository secret and protected
  environment are configured. No secret, webhook, Render service, Cloudflare
  Worker, or deployment is modified by this PR.
