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

This document defines the intended collaboration contract. It does not itself connect ChatGPT to LINE, add an API integration, dispatch a workflow, resume the distributed Loop, or authorize code changes outside this documentation file. Existing app.py routing and GitHub workflows must be inspected and tested before claiming end-to-end availability.
