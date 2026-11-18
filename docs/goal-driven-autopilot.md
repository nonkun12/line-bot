# Goal-driven autonomous continuation

## User-visible behavior

A goal remains active until every acceptance criterion is explicitly verified
and linked to evidence. The controller then reports COMPLETE. If work remains,
it selects exactly one eligible task and returns CONTINUE. It does not wait for
a user to say "next" between ordinary, pre-authorized tasks.

## Control cycle

1. Read the durable goal, task graph, safety policy, and kill switch.
2. Validate the goal schema and all task IDs/dependencies.
3. Reconcile any IN_PROGRESS task before selecting new work.
4. Stop on FAILED/HELD work; never retry or release it implicitly.
5. Select one dependency-ready task deterministically by priority and task ID.
6. Permit only allowlisted task kinds with explicit task-bound authorization.
7. Execute in a separately integrated runner with bounded time, path, and task limits.
8. Verify tests and independent evidence; only then mark the task complete.
9. Re-evaluate the goal and continue on the next scheduled controller tick.

## Safety boundaries

- MERGE, DEPLOY, permission changes, secret changes, and production writes are
  always rejected by this planner.
- READ_ONLY, TEST, and DRAFT_PR are not implicitly authorized; the selected
  task must carry explicit authorization.
- One task per decision; no unbounded recursion or self-dispatch.
- Kill switch or failed safety gate returns HOLD.
- Missing evidence never satisfies an acceptance criterion.
- FAILED, HELD, and IN_PROGRESS tasks block new selection until reconciled.
- The planner is pure: no file writes, state persistence, queue mutation,
  workflow dispatch, task execution, retries, merge, or deployment.

## Deployment plan

This PR adds only the pure decision engine and tests. It does not turn on a new
schedule or connect the planner to the production workflow. Integration must
be a separate reviewed change that:
- reuses the existing single schedule owner and serialized concurrency group;
- persists goal/task state with atomic compare-and-swap or an equivalent
  single-writer guarantee;
- uses stable idempotency keys, leases, stale-claim recovery, bounded retry,
  and a dead-letter/HOLD path;
- records scheduled tick, workflow start, task claim, and evidence-backed task
  completion as distinct events;
- keeps AUTO_APPLY_PATCH=false and AUTO_DEPLOY=false;
- proves duplicate workers cannot claim the same task and that restart recovery
  is durable before production use.

GitHub Actions schedules are best-effort, not a 24/7 uptime guarantee. This
architecture can continue remotely while a personal Mac is powered off, but
local-only models and tools cannot run while that Mac is off.
