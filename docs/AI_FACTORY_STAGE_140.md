# Stage 140: end-to-end self-expanding AI Factory

Stage 140 provides one entry point from capability requirements to pending
specialist-agent candidates:

1. Compare explicit requirements with enabled capability inventory.
2. Identify gaps with stable IDs and evidence.
3. Bind each gap to the local Architect.
4. Run the bounded four-role collaboration and candidate factory.
5. Generate artifacts with the local Builder.
6. Execute tests only in the pinned, network-disabled Docker sandbox.
7. Require a separate local-model Reviewer and the independent evidence gates.
8. Record successful candidates in the metadata-only pending catalog.

Safety gates (kill switch, HOLD, evidence, budget, max four candidates) are
checked before model invocation. Existing enabled capabilities are not rebuilt.
Candidates remain PENDING_HUMAN_APPROVAL and zero-privilege.

This stage is an on-demand runtime, not a scheduler or durable service. It does
not approve, register, activate, grant permissions, merge or deploy agents.
Live local models, Docker daemon and external human approval are not tested by
the fake-client unit tests.
