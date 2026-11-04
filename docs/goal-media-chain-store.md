# Durable audiovisual Goal-chain state

The agents/media goal-job-chain store persists validated audiovisual-to-game sprint plans and their derived evidence snapshots in the existing SQLite database.

## Guarantees

- A Goal ID is bound to one LINE/user owner and one canonical plan hash.
- Repeating the same create request returns the existing chain; a different owner or changed plan is rejected.
- Evidence updates use optimistic version checks and an append-only event history.
- Exact retries are idempotent. Conflicting stale updates fail closed.
- Completed, human-approved, and HOLD evidence cannot be removed through this API.
- State is re-derived by the deterministic Goal chain state module; downstream stages remain blocked until dependencies are completed and required human gates are approved.
- State reads are owner-scoped.

## Deliberate boundary

This is durable state/checkpoint persistence, not a worker or dispatcher. It does not create rows in the generic jobs queue, because the current generic worker can claim unrelated jobs and its default executor is a dry run. It does not enqueue, execute, approve, clear HOLD, modify media, publish, merge, or deploy. A dedicated Goal-media worker and an explicitly authorized LINE command should be added only after their execution and idempotency contracts are independently tested.

## API

- create_or_resume_goal_chain(user_id, plan)
- get_goal_chain(user_id, goal_id)
- record_goal_chain_evidence(user_id, goal_id, expected_version=..., completed_job_ids=..., approved_gate_job_ids=..., held_job_ids=...)
- get_goal_chain_history(user_id, goal_id)
