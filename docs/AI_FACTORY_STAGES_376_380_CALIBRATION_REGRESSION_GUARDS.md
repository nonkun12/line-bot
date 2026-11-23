# AI Factory Stages 376–380: Calibration and Regression Guards

## Scope

Proposal-only statistical validation gates for declared calibration bins, confidence
intervals, subgroup score disparities, directional metric regressions, and an aggregate
readiness result.

## Stages

- **376 — Calibration error:** computes count-weighted expected calibration error from
  caller-declared confidence/accuracy bins and enforces a maximum.
- **377 — Confidence interval validity:** checks finite [0,1] bounds and that point
  estimates lie inside each interval.
- **378 — Subgroup disparity:** enforces minimum declared sample sizes and a maximum
  max-minus-min score gap.
- **379 — Metric regression:** compares baseline/current values with an explicit
  higher-is-better or lower-is-better direction and per-metric tolerance.
- **380 — Integrated statistical guard:** PASS only when every subgate passes;
  otherwise BLOCKED.

## Safety and limitations

All values, bins, group definitions, directions, and tolerances are caller-supplied.
These checks do not validate sampling methodology, representativeness, causal validity,
statistical significance, data provenance, or whether subgroup definitions are complete.
The SHA-256 seal is a deterministic consistency checksum, not a trusted signature.
Execution authorization is always false. No experiments, tasks, training, model/weight
changes, permission changes, HOLD release, merge, or deployment are authorized.
This does not establish RSI/ASI capability.
