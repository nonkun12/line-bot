# ORCA distributed-loop handoff contract

## Status

Contract-only proposal. This change does not register tasks, call the D1 API,
dispatch GitHub Actions, claim work, execute a loop, or change any existing
LINE routing. Do not connect the payload builder to the webhook yet.

The current ORCA intake/worker path accepts only explicit
`アプリ開発:` tasks. The existing `distributed_loop_trigger.py` still
dispatches `distributed-autonomous-loop.yml` directly. PR #1331 places that
legacy workflow behind a fail-closed empty event allowlist. Therefore #1331
must remain unmerged until the replacement route is proven end-to-end.

## Typed task contract

A distributed-loop task is distinct from app development:

- `task_type = distributed_loop`
- `request_text` retains the exact recognized LINE command for auditability.
- `max_tasks` is derived only by the existing strict
  `_requested_max_tasks` parser (1–4); arbitrary prose and unsafe bounded
  commands are rejected.
- `user_id` must be a verified LINE user ID matching
  `U[0-9a-fA-F]{32}`.
- `source_event_id` is mandatory for webhook idempotency.
- `task_id` is constrained to the existing ORCA task identifier alphabet.

The pure payload builder and tests define this contract. They intentionally
perform no network I/O.

## Implementation status

Implemented in stacked Draft PR #1337 (based on #1333):

1. Migration 0006 adds constrained task type and max-task count to tasks and
   approvals. Existing rows default to `app_development` and `max_tasks=1`;
   no legacy task is promoted to a loop.
2. D1 task creation validates the exact recognized loop command and 1–4 bound.
   Duplicate LINE event checks include owner, body, task type, and bound.
3. App-development approval protocol v1 remains compatible. Distributed-loop
   approval protocol v2 binds task ID, request hash, owner, task type, max-task
   count, issue/expiry, and nonce.
4. The generic worker list defaults to `app_development`. The generic claim
   endpoint rejects `distributed_loop` with HTTP 409 until a dedicated
   executor is implemented. This is an intentional fail-closed barrier.

Still required before activation:

5. Extend the actual LINE webhook intake with a separate exact-command route.
   Read-only status requests must remain read-only; app-development intake
   must remain unchanged. Bind the verified LINE event owner and event ID.
6. Implement a dedicated distributed-loop worker handler. It must not pass
   loop commands through the app generator. It must enforce the 1–4 cap,
   recheck Global HOLD before every external write, and produce Task ID-scoped
   evidence.
7. Add end-to-end isolated tests for signed webhook → D1 intake → owner
   approval → dedicated claim → bounded execution → completion/outbox.
8. Keep the existing direct-dispatch route available until replacement
   verification is complete. Only after operator-approved cutover may the
   legacy workflows be disabled. Never merge #1331 as a shortcut.

## Safety invariants

- Global HOLD defaults to ON. Missing, unknown, or unavailable state blocks.
- No AI, timeout, or successful workflow conclusion may release HOLD.
- A queued task is registered, not claimed or running.
- Workflow success is not proof that a task passed; require task-level evidence.
- No auto-merge, deployment, production migration, or secret/permission change.
- D1 state cannot be made atomic with GitHub writes; retain explicit
  pre-write HOLD checks and report the residual TOCTOU limitation.
- GitHub-hosted runner quota and availability are not guaranteed; this path
  must not introduce paid inference or paid cloud dependencies.

## Tests in this contract change

`tests/test_orca_distributed_loop_intake.py` verifies command recognition,
the 1–4 task bound, task type separation, verified LINE owner, event ID, and
task ID validation. These are unit/contract tests only; they do not claim
end-to-end D1 or worker integration.
