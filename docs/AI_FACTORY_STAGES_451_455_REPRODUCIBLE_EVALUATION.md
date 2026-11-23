# AI Factory Stages 451–455: Reproducible Evaluation

- **451 — Run manifest:** required protocol, task set, evaluator/model/environment revisions, random seed, and dependency declarations.
- **452 — Rerun equivalence:** exact task coverage, output digest equality, and score tolerance comparison.
- **453 — Evaluator pinning:** exact expected version/revision matching.
- **454 — Audit chain:** ordered events with hash-linked payload declarations.
- **455 — Aggregate gate:** fail-closed reproducibility-readiness record.

## Safety and limitations
All manifests, outputs, digests, versions, and audit events are caller-supplied. Repeated declared output hashes do not prove the runs actually occurred or were independent. A hash-linked chain detects accidental or unsophisticated tampering only when its anchor is trusted; no trusted anchor or signature is provided here. This gate does not verify provenance or certify reproducibility. No model execution, training, experiments, model/weight changes, policy or permission changes, production actions, merge, or deployment.
