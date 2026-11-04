# Goal media job-chain state

`agents.media.goal_job_chain_state.derive_goal_job_chain_state` turns the
existing audiovisual-to-game sprint plan into a deterministic readiness view.

## State rules

- `READY`: every dependency is complete and every dependency human gate is approved.
- `BLOCKED`: one or more dependencies are incomplete or awaiting approval.
- `AWAITING_HUMAN_APPROVAL`: this stage completed and its declared gate is pending.
- `HOLD`: this stage or an upstream dependency is held; HOLD propagates downstream.
- A completed stage cannot be accepted when a dependency is incomplete or unapproved.
- Cycles, unknown dependencies, unknown evidence IDs, and approvals before completion
  are rejected.

The returned `snapshot` contains only completed, approved, and held stage IDs.
A caller can persist that snapshot in the existing job checkpoint store and pass it
back on resume. The module itself is pure: it does not write checkpoints, enqueue
jobs, execute work, approve gates, clear HOLD, edit media, publish, merge, or deploy.

This is an incremental orchestration contract, not yet a live LINE-to-worker
execution integration. Job persistence and worker dispatch remain separate steps.
