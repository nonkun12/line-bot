# AI Factory Stages 366–370: Cross-run Validation Gates

## Scope

This proposal-only module adds deterministic checks for declared cross-run protocol
consistency, validator identity/lineage collisions, anomaly-rate bounds, cohort
coverage, and a fail-closed aggregate gate.

## Stages

- **366 — Cross-run consistency:** requires nonempty unique run IDs and one shared
  declared protocol digest.
- **367 — Independent-validator declarations:** requires at least two validators
  with unique declared IDs and lineage IDs. This does **not** prove independence.
- **368 — Anomaly-rate bound:** rejects invalid counts/denominators and rates above
  the caller-supplied maximum.
- **369 — Cohort coverage:** requires exact coverage of the declared cohort set.
- **370 — Integrated gate:** returns PASS only when all four checks pass; otherwise
  BLOCKED. The deterministic seal covers the returned check payload.

## Safety and limitations

All values are caller-supplied. Digests and unique declarations do not authenticate
origin, truth, independence, metric meaning, or chain of custody. The seal is a
consistency checksum, not a trusted signature. No task execution, experiment,
training, model/weight change, permission change, HOLD release, merge, or deployment
is authorized. Execution remains explicitly false; this is not evidence of RSI/ASI.
