# Stage 139: bounded AI Factory loop

- Wraps the Stage 130 orchestrator with Stage 138 pending-catalog submission.
- Rechecks kill switch, HOLD, evidence completeness, budget availability, and
  a hard maximum of four candidates before any orchestration call.
- Processes only caller-supplied capability gaps; it does not invent tasks or
  schedule itself.
- A candidate is cataloged only when the orchestrator returns a candidate and
  a matching reviewed AgentCreationRecord is available.
- Catalog rejection converts the candidate result to BLOCKED.
- Catalog entries remain metadata-only and PENDING_HUMAN_APPROVAL.

This controller has no timer, persistent state, approval bypass, registration,
activation, permissions, merge or deploy behavior.
