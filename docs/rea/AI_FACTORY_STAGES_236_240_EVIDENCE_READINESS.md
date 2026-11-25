# AI Factory Stages 236–240 — Evidence Readiness

All stages are deterministic, proposal-only checks. They do not execute experiments, change models, or grant runtime authority.

- **236 — Independent source corroboration:** requires at least two distinct source IDs per evidence ID and exact digest agreement. Source independence is asserted by identifiers; this helper cannot establish organizational or technical independence.
- **237 — Evaluator drift:** compares bounded calibration metrics for the expected evaluator identity and a minimum sample count. It flags threshold breaches; it does not establish evaluator validity or calibration-set representativeness.
- **238 — Preregistration:** requires a frozen hypothesis, primary metric, dataset/suite digests, analysis/randomization plan, sample size, success threshold, explicit safety guardrails, timezone-aware registration time, and an explicit no-outcomes-observed declaration.
- **239 — Retention manifest:** validates artifact digests, provenance references, unique IDs, timezone-aware creation/retention windows, and produces a canonical SHA-256 manifest digest. It does not store artifacts or enforce retention.
- **240 — Readiness summary:** requires all four prior gates to pass and emits a separate-review recommendation only. It does not authorize execution or state transitions.

HOLD fails closed at every stage. Malformed, missing, conflicting, stale/expired, non-finite, or insufficient evidence is rejected. All outputs explicitly deny task execution, experiment execution, model changes, merge/deploy, and HOLD release.

Important limits:
- Source IDs do not prove independence; evidence sources must be independently governed outside this module.
- Evaluator drift checks depend on caller-supplied calibration data and declared evaluator identity.
- Preregistration is validated, not immutably timestamped or externally notarized.
- The retention manifest is a digest only; durable storage, access control, and deletion policy remain external.
- A readiness result is not an RSI/ASI achievement or evidence of actual capability gain.
