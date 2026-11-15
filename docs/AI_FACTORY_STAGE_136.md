# Stage 136: independent reviewer

- Adds a local-model reviewer consuming candidate files and passing sandbox evidence.
- Review input includes a deterministic SHA-256 digest over sorted paths and contents.
- Requires strict JSON with boolean approval and bounded findings/blockers.
- Any blocker downgrades approval; malformed output fails closed.
- Refuses candidates whose sandbox report did not pass.
- A wiring guard rejects reuse of the Builder client for review.

The reviewer is not human approval. It cannot register, activate, grant permissions,
merge, or deploy. Model review is fallible and must be combined with tests and
explicit human approval for activation.
