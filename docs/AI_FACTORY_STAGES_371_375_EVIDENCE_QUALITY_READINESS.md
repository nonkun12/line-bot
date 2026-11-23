# AI Factory Stages 371–375: Evidence Quality and Readiness

## Scope

Proposal-only deterministic checks for evidence freshness, metric-schema compatibility,
field missingness, required evidence-category coverage, and an aggregate readiness gate.

## Stages

- **371 — Evidence freshness:** rejects empty evidence, malformed timestamps, future
  timestamps, and records older than a caller-supplied age bound.
- **372 — Metric-schema compatibility:** requires a shared nonempty declared schema digest.
- **373 — Missingness bound:** validates field counts and enforces a declared maximum
  missingness rate.
- **374 — Evidence-category coverage:** requires exact coverage of declared categories.
- **375 — Aggregate readiness:** PASS only when every subgate passes; otherwise BLOCKED.

## Safety and limitations

All timestamps, digests, counts, and categories are caller-supplied declarations.
These checks do not authenticate evidence origin, timestamp accuracy, schema semantics,
or completeness of the real-world evidence universe. The SHA-256 seal is a deterministic
consistency checksum, not a trusted signature. Execution authorization is always false.
No experiments, tasks, training, model/weight changes, permission changes, HOLD release,
merge, or deployment are authorized. This does not establish RSI/ASI capability.
