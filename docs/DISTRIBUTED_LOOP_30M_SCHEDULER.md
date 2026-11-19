# Distributed LOOP 30-minute scheduler

This scheduler checks every 30 minutes and dispatches at most one bounded run of
`distributed-autonomous-loop.yml`.

## Safety behavior

- Dispatches the trusted `main` workflow only; the scheduler branch is not used
  as the execution source.
- Stops when `CONTROL_TOWER_KILL_SWITCH=true` or `.autonomous-loop.stop` exists.
- Stops when another distributed loop is queued or running.
- Dispatches with `max_tasks=1`; the target workflow retains its own queue refill,
  explicit `execution_approved` catalog checks, issue execution-approval label,
  Recovery AI HOLD / resume-review checks, evidence validation, and
  `AUTO_APPLY_PATCH=false` / `AUTO_DEPLOY=false` controls.
- Does not clear HOLD, create approval, merge, deploy, or change the durable queue.
- The scheduler concurrency group prevents a backlog of scheduler runs.

## Minute budget

Before dispatch, the scheduler sums started GitHub Actions job durations visible
in this repository for the current UTC calendar month. The default ceiling is
1,800 repository-visible minutes, providing a margin below the requested
2,000-minute stop. It counts each started job with per-job whole-minute rounding
and includes in-progress jobs up to the current time. Invalid or unavailable
usage evidence blocks dispatch.

**Scope limitation:** this is a repository-local estimate, not GitHub's
account-wide billing meter. It cannot see usage in other repositories or
organizations. Configure a lower ceiling if those workflows also consume the
same account allowance. Do not interpret the estimate as an exact billing
balance.

## Activation and verification

The workflow is scheduled on GitHub's UTC cron at minute 0 and 30. GitHub may
delay scheduled events under load. The first successful scheduler run must be
verified in Actions; a workflow file on a pull-request branch is not active
until merged to the default branch. The scheduler itself never merges or deploys.
