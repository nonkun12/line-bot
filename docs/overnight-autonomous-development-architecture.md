# Overnight Autonomous Development Architecture

## Goal

Build a generic overnight autonomous development system. It must not be limited to Todo applications. A LINE user can request a new application, API, feature, bug fix, refactor, or new agent, and the system creates a persistent development Job.

## Core principle

The persistent Job is the outer state machine. Individual AI Workers are short-lived execution units. Do not depend on one long-running LangGraph invocation surviving the night.

## Intended lifecycle

1. LINE request is classified as a development request.
2. A persistent development Job is created.
3. The Job Orchestrator claims the Job and executes one bounded stage/cycle.
4. Development/implementation runs in an isolated worktree.
5. Tests are executed.
6. If tests fail: Debug -> Fix -> Patch -> Test is repeated automatically.
7. Stop conditions protect against infinite loops: maximum retry count, no-progress detection, and total Job time limit.
8. When tests pass, run review/verification.
9. Commit is allowed only after required gates succeed.
10. Deploy remains approval-gated initially; automatic deployment can be enabled explicitly later.
11. After deployment, perform verification. Deployment failures have a much smaller retry budget and should prefer rollback over repeated autonomous production changes.
12. The Job ends with a durable status and a concise LINE report.

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
- pending_review
- succeeded
- failed_max_retries
- failed_no_progress
- failed_timeout
- failed_deploy_rollback
- stopped_by_human

Each cycle must record a checkpoint containing at least:

- stage
- cycle number
- changed files summary
- test pass/fail summary
- error summary/signature when applicable
- worker result summary

`retry_count` and `max_retries` must be actively enforced by the Orchestrator.

## No-progress protection

A test failure should produce an error signature based on stable information such as failing test names and normalized error messages. If the same failure repeats without meaningful change, stop the Job as `failed_no_progress` rather than consuming all retries.

## Isolation

Before concurrent development Jobs are supported, each Job must have its own Git worktree or isolated clone. A shared `REPO_WORKDIR` is not safe for parallel Jobs.

The Worker runtime itself must not depend on the target Job modifying the same working tree from which the Worker is currently executing.

## Existing Agents

The existing Debug Agent is part of the intended system. Its current adapter collects error information, analyzes it, and generates a fix suggestion. Existing Fix, Patch, Test, Commit, and Deploy nodes should be reused where practical rather than duplicated.

## Safety

Existing gates must remain intact:

- Patch application must remain explicitly controlled.
- Commit must require successful tests.
- Deploy must remain approval-gated by default.
- Production/deployment recovery must have a much lower retry budget than ordinary test/fix cycles.

Do not remove these gates merely to make the overnight loop autonomous.

## Implementation order

1. Connect development Jobs to the Worker executor.
2. Implement the outer Orchestrator state machine.
3. Implement Test -> Debug -> Fix -> Patch -> Test looping with retry/no-progress/time limits.
4. Add per-Job worktree isolation.
5. Persist detailed checkpoints and status reporting.
6. Add review/approval integration.
7. Add deployment verification and conservative rollback handling.
8. Move Job persistence to Postgres and add leases/worker IDs before true multi-worker concurrency.
9. Only then scale to multiple specialized workers/processes.

Existing LINE Notes, Memory, Reminder, and other stable functionality must not be changed unnecessarily.
