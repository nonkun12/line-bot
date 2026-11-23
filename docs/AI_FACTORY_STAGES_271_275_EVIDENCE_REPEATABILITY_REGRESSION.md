# AI Factory Stages 271–275: Evidence Provenance and Repeatability

## Stages

- **271 — Task-bank custody receipt:** validates receipt structure, timezone-aware receipt time, receipt digest, and linkage to the expected task-bank manifest. It explicitly does not authenticate the external custodian or provide trusted timestamping.
- **272 — Execution evidence receipt:** binds input/output, model-configuration, task-bank, and runtime-fingerprint digests. It requires separate observed-field and declared-field lists so provenance is visible.
- **273 — Multi-round replication:** requires at least three positive rounds with distinct task-set digests and evaluator declarations under one protocol digest.
- **274 — Capability regression guard:** compares sealed baseline and candidate multi-domain results on exactly the same domains. It blocks missing/invalid evidence and detects a domain falling below its practical-gain threshold or beyond the allowed regression tolerance.
- **275 — Research-plan generator:** ranks proposal-only follow-up work using declared information gain, uncertainty, weakest-domain ordering, and a cost ceiling. It never launches the work.

## Evidence boundaries

- Receipt IDs, authority IDs, timestamps, evaluator IDs, observed-field labels, and evidence digests are supplied by callers. Structural validation is not external authentication.
- SHA-256 detects content changes relative to a supplied digest; it is not a signature, trusted timestamp, proof of custody, or proof that an execution occurred.
- “Observed” fields are provenance labels provided by the caller. This module cannot independently attest that a sensor, runtime, evaluator, or external service observed them.
- Three rounds improve the repeatability protocol but do not prove institutional independence, absence of collusion, hidden task sets, or generalization.
- Stage274 compares supplied lower bounds; it does not recompute raw observations or repair upstream statistical assumptions.
- Stage275 uses declared information gain, uncertainty, and cost estimates. Rankings are planning suggestions, not measured utility or execution approval.
- No stage establishes RSI or ASI.

## Safety

Every stage fails closed unless HOLD is explicitly false. All task execution, experiment execution, model changes, merge/deploy, and HOLD-release flags remain false. No experiment, training, model execution, weight mutation, merge, deployment, or HOLD release is performed.
