# Overnight Autonomous Development Architecture

## Goal

Build a generic overnight autonomous development system. It must not be limited to Todo applications. A LINE user can request a new application, API, feature, bug fix, refactor, or new agent, and the system creates a persistent development Job.

## Core principle

The persistent Job is the outer state machine. Individual AI Workers are short-lived execution units. Do not depend on one long-running LangGraph invocation surviving the night.

## Intended lifecycle

1. LINE request is classified as a development request.
2. A persistent development Job is created.
3. The Job Orchestrator claims the Job and executes one bounded stage/cycle.
4. Development/implementation runs in an isolated per-Job Git worktree.
5. Tests are executed.
6. If tests fail: Debug -> Fix -> Patch -> Test is repeated automatically.
7. Stop conditions protect against infinite loops: maximum retry count, no-progress detection, and total Job time limit.
8. When tests pass, commit the changes in the Job worktree.
9. If GitHub publishing is explicitly enabled, push the Job branch and create/reuse its PR. Publishing is disabled by default with `AUTO_PUBLISH_JOB_BRANCH=false`.
10. Run the GitHub CI gate against the Job commit. The Worker waits until the required Pytest, Overnight Worker Test, and AI Code Review workflows have completed successfully. The GitHub AI Code Review workflow itself is intentionally network-independent; it verifies that a reviewable diff exists.
11. After GitHub CI passes, the Worker-side Review Agent runs an actual Groq-based code review against the current `origin/main...HEAD` diff. The review returns PASS/FAIL plus structured findings. Configuration errors are terminal; transient request failures may be retried.
12. The `commit` approval gate is presented only after the PR exists and both GitHub CI and the Worker-side AI review pass. A LINE approval is not treated as a merge by itself: the Worker calls GitHub and confirms the PR is actually merged.
13. Deploy is allowed only after GitHub reports the PR as merged. `AUTO_DEPLOY=false` remains the safe default, so production deployment requires the separate deploy gate/explicit activation.
14. After deployment, perform verification. Deployment failures have a much smaller retry budget and should prefer rollback over repeated autonomous production changes.
15. The Job ends with a durable status and a concise LINE report.

## GitHub publication and approval model

Job branches are named `worker/job-{job_id}` and are isolated in a dedicated worktree. The Worker uses local Git for the commit and `git push` for publication; the GitHub REST API is used for PR lookup/creation, CI/review status lookup, merge execution, and merge-state verification.

GitHub credentials are supplied to the Worker through environment variables and are never written to the repository remote URL. Set `AUTO_PUBLISH_JOB_BRANCH=true` only after GitHub credentials and repository protections have been verified.

The release sequence is intentionally:

`tests passed -> commit -> push/PR -> GitHub CI -> Worker AI Review -> LINE commit approval -> GitHub merge -> LINE deploy approval -> deploy`

The `commit` approval is therefore the human gate for the proposed change becoming part of `main`. The authoritative merge state is always GitHub, not the LINE approval record.

## Worker-side AI Review

The Worker-side Review Agent is the substantive semantic code-review gate. It refreshes `origin/main` immediately before calculating the diff so the review reflects the current main branch. It sends only a bounded diff to Groq and expects strict JSON with `PASS` or `FAIL` plus findings.

The GitHub Actions workflow named `AI Code Review` is deliberately lightweight and independent of external model availability. Its role is to guarantee that the PR has a non-empty reviewable diff and to provide a stable CI gate. The actual AI judgment is performed by the Worker where the same production Groq configuration is available.

## Worker leases and restart safety

Each running Job has a `worker_id` and lease deadline. Only the current lease owner may finalize or retry a running Job. When a lease expires, the Job is requeued and the stale worker loses the ability to overwrite its state.

A Job's LangGraph checkpoint records progress, but it is not treated as the sole source of truth. When a development worktree disappears after Worker restart, the Worker can rebuild it from the Job branch stored locally or on the Git remote when that branch has already been published.

Uncommitted changes that never reached GitHub cannot be reconstructed after complete ephemeral-disk loss. For that reason, durable remote commits are the strongest restart checkpoint for work that has already been committed.

## Worker roles

The initial implementation may use one worker process with role-specific stages. The architecture must allow specialized workers later:

- Development Worker
- Test Worker
- Debug Worker
- Fix/Patch Worker
- Review Worker
- GitHub/Commit Worker
- Deploy/Verify Worker

Specialized workers do not need to be separate services initially. A common worker executable with stage routing is acceptable until concurrency requires independent processes.

## Separation of responsibilities

### Conversational Supervisor

Handles one LINE message and selects the normal conversational Agent. It is not the overnight Job Orchestrator.

### Job Orchestrator

Handles durable Job state and selects the next development stage. It must use the Job record and checkpoints rather than conversation state.

### Worker

Executes one bounded stage and returns structured output. It must be safe to rerun after a process crash.

## Required Job controls

The Job state machine should support explicit terminal states such as:

- pending
- running
- waiting_approval
- succeeded
- failed_max_retries
- failed_no_progress
- failed_timeout
- failed_deploy
- stopped_by_human

Each cycle must record a checkpoint containing at least:

- stage
- cycle number
- changed files summary
- test pass/fail summary
- review status and required workflow results
- AI review verdict/findings when applicable
- error summary/signature when applicable
- worker result summary

`retry_count` and `max_retries` must be actively enforced by the Orchestrator.

## No-progress protection

A test failure should produce an error signature based on stable information such as failing test names and normalized error messages. If the same failure repeats without meaningful change, stop the Job as `failed_no_progress` rather than consuming all retries.

## Isolation

Before concurrent development Jobs are supported, each Job must have its own Git worktree or isolated clone. A shared `REPO_WORKDIR` is not safe for parallel Jobs.

The Worker runtime itself must not depend on the target Job modifying the same working tree from which the Worker is currently executing.

## Existing Agents

The existing Debug Agent is part of the intended system. Its current adapter collects error information, analyzes it, and generates a fix suggestion. Existing Fix, Patch, Test, Commit, Publish, Review, Merge, and Deploy nodes should be reused where practical rather than duplicated.

## Safety

Existing gates must remain intact:

- Patch application must remain explicitly controlled.
- Commit requires successful tests.
- GitHub publication is explicitly opt-in through `AUTO_PUBLISH_JOB_BRANCH`.
- GitHub CI must pass before merge approval.
- Worker-side AI Review must return PASS before merge approval.
- Merge requires the LINE approval gate and a successful GitHub merge confirmation against the expected Job branch/commit.
- Deploy must remain approval-gated and `AUTO_DEPLOY` must remain false unless intentionally enabled.
- Production/deployment recovery must have a much lower retry budget than ordinary test/fix cycles.

Do not remove these gates merely to make the overnight loop autonomous.

## Implementation order

1. Connect development Jobs to the Worker executor.
2. Implement the outer Orchestrator state machine.
3. Implement Test -> Debug -> Fix -> Patch -> Test looping with retry/no-progress/time limits.
4. Add per-Job worktree isolation.
5. Persist detailed checkpoints, leases, and status reporting.
6. Add GitHub branch publication and PR lifecycle.
7. Add the GitHub CI/review gate before merge approval.
8. Add Worker-side AI semantic review.
9. Add merge-state verification and deploy approval.
10. Add deployment verification and conservative rollback handling.
11. Move Job persistence to Postgres before true multi-worker scale and increase heartbeat/lease coordination as concurrency grows.
12. Only then scale to multiple specialized workers/processes.

Existing LINE Notes, Memory, Reminder, and other stable functionality must not be changed unnecessarily.
