# LINE + ChatGPT Collaboration for ASI Development

## Goal

Use LINE as the always-available command and status interface, and ChatGPT as an optional research, architecture, analysis, and planning partner. The two interfaces must share one durable task/evidence model; users should not need to repeat task context.

## Roles

- **LINE / line-bot**: accept authenticated user instructions, create durable task requests, show status, return results, and route explicitly authorized bounded work to existing GitHub workflows.
- **ChatGPT**: help decompose research questions, compare designs, inspect evidence supplied or retrieved through connected tools, draft experiments, analyze benchmark results, and propose next tasks.
- **GitHub / distributed Loop / REA**: execute bounded jobs, preserve run identity and artifacts, test changes, and record machine-verifiable outcomes.
- **Control Tower / Orca**: aggregate queue, run, safety, and capability metrics.

ChatGPT is not assumed to have direct access to the LINE runtime or private repository in every session. The integration must not claim messages or actions were synchronized unless a durable record confirms it.

## Shared task envelope

Every cross-interface task should carry:
- task_id (stable, unique)
- origin (line, chatgpt, scheduler, or operator)
- objective and canonical instruction hash
- repository and base commit
- exact allowed_paths and their canonical hash
- risk class and execution policy
- status (QUEUED, RUNNING, PASS, FAIL, NO_CHANGE, BLOCKED)
- run_id / run_attempt and artifact references
- REA scanner result and test result
- created_at / updated_at timestamps

Do not place secrets, LINE access tokens, personal data, or unrestricted credentials in task envelopes or model prompts.

## Operating flow

1. User sends a request through LINE or develops a plan with ChatGPT.
2. Convert the request into a task envelope and persist it before acknowledging dispatch.
3. ChatGPT may propose or refine task instructions; proposals are not execution authorization.
4. LINE routes only explicitly prefixed development requests to the existing bounded development workflow. Read-only status and analysis commands must never dispatch write-capable Actions.
5. The runner checks authorization, exact task identity, allowed paths, base SHA, budget, and kill switch before execution.
6. REA and tests produce evidence bound to the task and exact run. Missing, stale, mismatched, replayed, or failed evidence yields BLOCKED.
7. Persist the result and make the same result visible to LINE and available to ChatGPT for analysis.
8. ChatGPT can analyze outcomes and propose follow-up tasks. It cannot clear HOLD, bypass repository protections, merge, deploy, or change permissions.

## LINE command contract (target behavior)

- `ASI開発: <objective>`: create a bounded research/development task; do not imply immediate execution if queued or blocked.
- `Loop状況`: read-only queue/run/evidence status.
- `REA検証`: read-only latest REA evidence summary.
- `能力測定`: request or report a benchmark run only when a benchmark is configured and authorized.
- `失敗分析`: analyze persisted failure evidence without dispatching repairs.
- `自律開発: <objective>`: create a development request subject to scope and authorization checks.
- `停止`: invoke the existing emergency-stop behavior.

These are target commands, not a claim that every command is currently implemented. Unknown commands must fail closed and explain the supported route.

## ChatGPT collaboration contract

- Use ChatGPT for research, decomposition, design review, test planning, and interpretation of benchmark evidence.
- Transfer conclusions back as a task proposal containing objective, acceptance criteria, test plan, risks, and allowed paths.
- Do not require a paid API or automatic cloud fallback. A future API bridge is optional and must be explicitly configured, budget-limited, privacy-reviewed, and disabled by default.
- Without an API bridge, the user can copy/share the task summary between ChatGPT and LINE; the durable task_id is the correlation key.
- Never represent a manual ChatGPT conversation as an automated agent-to-agent connection.

## Safety invariants

- Read-only by default; explicit development prefix required for write-capable routing.
- AUTO_APPLY_PATCH=false and AUTO_DEPLOY=false remain the defaults.
- No auto-merge, deploy, permission changes, secret access, or branch-protection bypass.
- Existing HOLD and human-review requirements remain in force. A second AI opinion does not satisfy a human-review requirement.
- Evidence failure, ambiguity, scope drift, stale state, or unavailable services => BLOCKED.
- Do not automatically resume old held tasks in bulk.
- A successful workflow is not a successful task unless task-level acceptance evidence is complete.

## Capability measurement

Track on a fixed benchmark set:
- task completion rate by difficulty
- REA pass rate and test pass rate
- repair success rate and regression rate
- recurrence by failure fingerprint
- time and compute per accepted task
- false-positive / false-negative rates only when independently labeled ground truth exists

Compare against a frozen baseline and holdout tasks. Do not count more loop iterations as capability improvement unless quality improves without safety regressions.

## Current implementation boundary

The current branch now propagates one stable 32-character task ID from the LINE dispatcher into the governed GitHub Actions workflow. The workflow binds that same ID to the task-bound execution approval, run name, final report, PR description, optional Google Sheets ledger record, 90-day report artifact, and LINE completion notification. Legacy workflow callers may omit the input; the workflow then generates its own ID.

The workflow artifact and GitHub run record provide a durable correlation trail, but this is not yet a complete shared task database or a LINE task-lookup command. Google Sheets persistence depends on its existing credentials/configuration. ChatGPT is not automatically connected to LINE; it can use the shared task ID and GitHub evidence when that information is provided or retrieved through an authorized GitHub connection.

## Verified integration baseline (2026-11-23)

Read-only inspection confirmed that:
- `app.py` already routes explicit Loop status requests through `request_distributed_loop` before general AI routing.
- `line_development.py` requires the configured LINE user allowlist before dispatching the governed development workflow.
- The dispatcher now creates a 32-character UUID task ID and sends it as the `task_id` workflow input. Retries within that dispatch reuse the same ID.
- The workflow uses the supplied ID as `AUTONOMOUS_TASK_ID` and `AUTONOMOUS_APPROVAL_TASK_ID`; it records the ID in its run name, report, PR description, optional Sheets record, report artifact name, and LINE completion message.
- A missing ID from legacy callers is supported: the workflow generates an ID before task-bound approval.
- The latest full Pytest workflow for the current branch passed after the task ID test update. The workflow itself has not been dispatched as a live LINE development task.

## Remaining implementation order

1. Add a read-only LINE lookup by task ID, backed by GitHub workflow-run metadata and the task report artifact.
2. Make the sanitized task record retrievable for ChatGPT-assisted analysis using the same task ID.
3. Add a compact ChatGPT-to-LINE handoff format with objective, acceptance criteria, test plan, risks, and allowed paths.
4. Add end-to-end tests for task identity continuity, duplicate delivery, replay rejection, status-only non-dispatch, and evidence-bound terminal states.

Do not use the existing Mac-local pending queue as the canonical shared ledger; it is not shared by the hosted LINE and GitHub Actions runtimes. Do not claim automatic ChatGPT-to-LINE synchronization until a privacy-reviewed API bridge exists.
