# Distributed AI event ledger

The distributed autonomous loop emits a run-scoped JSONL handoff ledger after the
bounded task runner finishes. The ledger is uploaded as a 90-day Actions artifact
named `distributed-ai-event-ledger-<run_id>`.

Each queued task receives a `task.assigned` event. A task with a runner result
receives a terminal event attributed to the verifier; started work is recorded
only for non-blocked outcomes. Unexecuted queue entries remain assigned-only.
Events have deterministic SHA-256 IDs so an exported run can be deduplicated.

## Safety properties

- This is observability, not an execution or approval mechanism.
- It never adds execution approval, clears Recovery AI HOLD, changes the queue,
  launches another task, merges a PR, or deploys.
- Task identity comes only from an exact `task_id` / `id` match in the
  run-local runtime queue. Free-text diagnostics are not used to infer identity.
- Unknown or malformed result statuses fail closed as `task.failed`.
- Blocked and stopped tasks are not represented as started or completed.

## Current scope

This first increment provides a validated, per-run event record and artifact.
It does not yet provide a cross-run event database, live agent messaging, or
automatic assignment of a new task to another agent. Those require a durable
store and explicit recipient/authorization contracts; they should be added as
separate reviewed changes rather than inferred from a log entry.
