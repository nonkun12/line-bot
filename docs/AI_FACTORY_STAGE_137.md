# Stage 137: full AI Factory pipeline wiring

Stage 137 composes the concrete Stage 134 Builder, Stage 135 Docker sandbox,
and Stage 136 independent Reviewer into the Stage 133 orchestrator.

- Four distinct model identities are required for designer, architect, builder,
  and reviewer.
- Builder and Reviewer must also receive distinct client instances.
- The same Docker sandbox and model adapters are verified as the exact
  dependencies installed into AgentFactory.
- Existing independent TEST and REVIEW collaboration evidence gates remain
  mandatory; model-generated text cannot certify either gate.
- No tools, resource scopes, or human approval adapter are granted by default.

Tests validate composition with fake model clients and a fake process runner.
No real local-model or Docker daemon execution is claimed.
