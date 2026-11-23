# AI Factory Stages 381–385: Reproducibility and Robustness Controls

## Scope

Proposal-only checks for reproducibility-manifest completeness, perturbation coverage,
sensitivity bounds, repeated-run stability, and an integrated fail-closed gate.

## Stages

- **381 — Reproducibility manifest:** requires declared code, configuration, data,
  seed, and environment identifiers/digests.
- **382 — Perturbation coverage:** requires exact coverage of predeclared perturbation
  classes.
- **383 — Sensitivity bound:** limits absolute score changes under declared
  perturbations.
- **384 — Repeat-run stability:** bounds the range of repeated declared scores.
- **385 — Integrated gate:** PASS only when all four checks pass; otherwise BLOCKED.

## Safety and limitations

All inputs and identifiers are caller-supplied. Manifest digests do not prove that
the referenced code, data, environment, or seed were actually used. Declared
perturbation sets may omit relevant conditions; score stability does not establish
validity or generalization. The SHA-256 seal is a consistency checksum, not a trusted
signature. Execution authorization is always false. No experiments, tasks, training,
model/weight changes, permission changes, HOLD release, merge, or deployment are
authorized. This does not establish RSI/ASI capability.
