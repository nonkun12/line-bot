# AI Factory Stages 461–465: Improvement Attribution

- **461 — Paired comparison:** align protocol, task set, metric, and scoring method.
- **462 — Change isolation:** require one declared primary change and reject other uncontrolled changes.
- **463 — Improvement threshold:** evaluate a declared higher/lower-is-better metric and minimum gain.
- **464 — Guardrail regression:** enforce per-metric maximum degradation limits.
- **465 — Aggregate decision:** return READY_FOR_REVIEW only when all declarations pass; otherwise HOLD.

## Safety and limitations
All runs, changes, metrics, and thresholds are caller-supplied. Matching metadata and a single declared change do not prove causal attribution, actual isolation, statistical significance, or absence of hidden confounders. This is a proposal-only screening gate, not permission to alter a model or execute an experiment. No training, experiments, model/weight changes, policy/permission changes, production actions, merge, or deployment.
