# Stage 138: metadata-only pending agent catalog

- Accepts only REVIEWED AgentCreationRecord values with passing sandbox evidence
  and an approving independent review with no blockers.
- Rejects any requested tool or resource scope; Stage 138 candidates remain
  zero-privilege.
- Stores deterministic spec/artifact SHA-256 digests, artifact paths, and
  test/review evidence metadata. It does not store executable file contents.
- Candidate state is always PENDING_HUMAN_APPROVAL and enabled=false.
- Duplicate submissions are idempotent; conflicting names are rejected.

This is an in-memory catalog adapter, not durable persistence. It provides no
approval, activation, executor registration, permission grant, merge or deploy.
