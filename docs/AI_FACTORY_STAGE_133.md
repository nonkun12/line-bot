# Stage 133: four-role local-model orchestration

Stage 133 provides a composition root that wires Stage 132 local Ollama clients
through the Stage 131 end-to-end factory path.

## Runtime wiring

- A dedicated local model client produces the capability-gap AgentSpec.
- A separate local model client performs the DESIGN role.
- Another separate local model client performs the BUILD role.
- Independent TEST and REVIEW evidence gates are injected by the operator.
- The Stage 121 AgentFactory then runs its own builder, sandbox, and reviewer
  adapters before the orchestrator can return a candidate.

## Fail-closed behavior

- All four collaboration roles must have distinct identities.
- Missing TEST/REVIEW gates are rejected during construction.
- Failed TEST or rejected REVIEW blocks the pipeline before Stage 121 candidate
  generation.
- Stage 121 sandbox tests and reviewer must also pass independently.
- The model-generated AgentSpec is still constrained to empty tool/resource
  scopes by Stage 132 and the factory allowlists.
- The candidate remains AWAITING_APPROVAL; the factory has no configured
  human-approval gate, catalog registration or activation is not performed.

## Limits

The local model clients require an Ollama-compatible service on the same host
as the Python process. CI uses deterministic fakes and cannot prove the user's
local model is installed, loaded, or responding. Builder, sandbox, reviewer,
TEST and REVIEW are explicit injected adapters; Stage 133 does not fabricate
independent verification.

No scheduler, cadence, persistent state, GitHub Actions secrets, permissions,
merge, deployment, or production activation is changed.
