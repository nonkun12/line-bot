# AI Factory Stages 391–395: Generalization Evidence Gates

## Scope
- **391 — Exact slice coverage:** require unique, exact declared slice IDs and minimum sample counts.
- **392 — Worst-case improvement:** enforce a lower bound on every supplied slice improvement, not only an aggregate mean.
- **393 — Guardrail coverage:** require every declared guardrail and enforce direction-aware regression tolerances.
- **394 — Cohort replication:** require unique cohort IDs, a minimum cohort count, and a minimum improvement per cohort.
- **395 — Aggregate gate:** combine all checks and fail closed.

## Safety
All inputs are caller-supplied declarations and observations. These checks do not establish that slices or cohorts are representative, independent, correctly sampled, or authentic; nor do they prove causality, statistical significance, external validity, or generalization. Cohort IDs are labels, not proof of independence. SHA-256 is a deterministic consistency checksum, not a trusted signature.

The aggregate result is proposal-only. `execution_authorized` and `promotion_authorized` are always false. No experiments, training, model/weight changes, HOLD release, permission changes, production actions, merge, or deployment are performed. No RSI/ASI claim is made.
