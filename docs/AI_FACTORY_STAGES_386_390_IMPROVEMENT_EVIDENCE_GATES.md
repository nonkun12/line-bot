# AI Factory Stages 386–390: Improvement Evidence Gates

## Scope

Proposal-only controls for paired-sample alignment, minimum measured improvement,
guardrail metric degradation, benchmark comparability, and an integrated promotion
evidence gate.

## Stages

- **386 — Paired-sample alignment:** requires nonempty, unique, exactly matching
  sample IDs between candidate and baseline.
- **387 — Minimum improvement:** requires the caller-declared paired improvements
  to meet a minimum arithmetic mean.
- **388 — Guardrail metrics:** enforces per-metric degradation limits using explicit
  higher-is-better or lower-is-better direction.
- **389 — Benchmark compatibility:** requires matching benchmark, protocol, and
  metric-schema identifiers.
- **390 — Integrated evidence gate:** PASS only when all checks pass; otherwise
  BLOCKED. It never authorizes execution or promotion.

## Safety and limitations

The caller supplies sample IDs, paired deltas, benchmark identifiers, metric
directions, and thresholds. Matching IDs do not prove paired observations were
collected correctly; mean improvement alone does not establish statistical
significance, causality, or generalization. Matching benchmark declarations do not
authenticate the benchmark or protocol. The SHA-256 seal is a deterministic
consistency checksum, not a trusted signature. Execution and promotion authorization
are always false. No experiments, training, model/weight changes, permission changes,
HOLD release, merge, or deployment are authorized. This does not establish RSI/ASI.
