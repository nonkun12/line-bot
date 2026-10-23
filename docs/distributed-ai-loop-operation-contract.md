# Distributed AI Loop: operation contract

This document is the durable operator checklist for the free GitHub Actions loop. It supplements, and never overrides, the workflow's executable safety gates.

## Canonical entry point

- Workflow: `.github/workflows/distributed-autonomous-loop.yml` (name: **Distributed Autonomous Development Loop**).
- Manual run: GitHub Actions → this workflow → `Run workflow`; choose `max_tasks` from 1 through 4. Default is 1.
- Authorized PR comment: `/distributed-loop max_tasks=1` through `/distributed-loop max_tasks=4`, on a PR and by an owner/member/collaborator.
- LINE entry points are implemented in `distributed_loop_trigger.py`; they require an allowlisted user and configured GitHub Actions dispatch token. A reply must not claim a run started until a corresponding run is visible.
- Do not invent alternate workflow names or bypass the authorized trigger.

## Preflight and stop conditions

Before interpreting a run as progress, inspect the run's actual workflow and SHA, then inspect the task-level result and final report. The workflow itself must re-check the remote stop file, durable state, Recovery AI state, current queue/catalog, Control Tower kill switch, and bounded task limit.

Stop without retrying or advancing when any of these apply:
- remote stop file / Control Tower kill switch is active;
- Recovery AI HOLD, invalid/missing durable state, or invalid queue-progress evidence;
- task status is FAIL, BLOCKED, NOT_RUN, or required test/evidence is absent;
- state persistence/read-back or required publish gates fail;
- no trusted eligible candidate exists. Do not fabricate a task or bypass review/hold state.

A successful workflow conclusion alone is not sufficient: confirm the final report, task status, produced SHA, changed paths, and relevant test results.

## Durable evidence and recovery

- Workflow state branch: `autonomous-loop-state`; the workflow validates and reads back persisted Recovery AI / RAG / sanitized self-improvement state.
- Every run should be traceable by run URL/ID, base and produced SHA, task ID, PASS/FAIL/NO_CHANGE/NOT_RUN/BLOCKED, changed files, tests, persistence result, and stop reason. Use the run artifact and step logs as evidence.
- Google Sheets must be checked in the live destination when the requirement is to prove a row was written. An artifact or a workflow step marked successful is not independent proof of a live row.
- For a failed run, investigate its original logs and evidence first; make a bounded reviewed fix. Do not loop-retry blindly.
- If a task is held, resume only that exact task after the cause is fixed and the workflow's explicit confirmation gate is satisfied.

## Non-negotiable safety

- `AUTO_APPLY_PATCH=false` and `AUTO_DEPLOY=false` remain required.
- No merge or deploy without separate explicit authorization, successful required checks, diff review, and evidence. A draft PR is reviewable work, not approval.
- Prefer existing/free GitHub Actions facilities. Do not introduce paid APIs or services for loop continuity.
- If the run cannot actually be dispatched or its run ID cannot be verified, report that honestly; never claim it is running.

## Current checkpoint (2026-10-23)

- Loop run [39905314048](https://github.com/nonkun12/line-bot/actions/runs/39905314048) completed one bounded task as PASS; REA was OBSERVE_ONLY and did not authorize merge/deploy.
- Its output is in draft [PR #821](https://github.com/nonkun12/line-bot/pull/821), not merged. The Pytest workflow run [39905850835](https://github.com/nonkun12/line-bot/actions/runs/39905850835) succeeded.
- Historical failed run [39902715053](https://github.com/nonkun12/line-bot/actions/runs/39902715053) is tracked by [issue #818](https://github.com/nonkun12/line-bot/issues/818). Its Google Sheets live-row verification is still a separate outstanding check.
- This document is an operating contract, not a claim that every completion criterion is already implemented or independently verified.
