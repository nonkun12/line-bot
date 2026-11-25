# AI Factory Stages 231–235 — Safe Proposal Gates

All stages are deterministic, proposal-only validators.

- **231 — Evidence freshness:** checks timezone-aware timestamps against an explicit evaluation time and maximum age. Future timestamps and naive timestamps fail closed.
- **232 — Evidence revalidation:** compares exact expected/actual digest manifests and requires caller-confirmed signature verification. It does not perform cryptography.
- **233 — Safety policy:** requires explicit restrictive controls: safety gate on, approval required, and automatic execution/training/model mutation/merge/deploy/HOLD release disabled.
- **234 — Candidate deduplication:** creates stable SHA-256 fingerprints from normalized category/action/target fields. A fingerprint is an identity aid, not proof of semantic equivalence.
- **235 — Review gate:** assembles a review package only when all prerequisite statuses pass. It does not authorize task execution.

HOLD fails closed in every stage. Missing evidence, malformed timestamps, digest mismatch, permissive or missing policy fields, and incomplete candidate identities are rejected.

No task/experiment execution, training, model mutation, rollback, queue mutation, HOLD release, merge, or deployment is performed or authorized. Signature verification is an external caller responsibility. A review-ready status is not approval and is not evidence of RSI/ASI or actual capability improvement.
