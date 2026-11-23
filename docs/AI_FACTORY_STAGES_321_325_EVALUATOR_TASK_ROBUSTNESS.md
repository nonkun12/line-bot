# AI Factory Stages 321–325: Evaluator and Task-Level Robustness

- **321 — Leave-one-evaluator-out:** checks whether the declared gain threshold survives removal of each evaluator's aggregate contribution.
- **322 — Paired task gains:** validates paired bounded scores and enforces both mean gain and positive-task fraction thresholds.
- **323 — Domain gain floors:** requires every declared domain to meet minimum paired-task coverage and mean-gain floor.
- **324 — Cross-domain dispersion:** bounds the spread between sealed per-domain mean gains.
- **325 — Integrated gate:** requires all four sealed checks and yields proposal eligibility for separate review only.

## Limitations

All evaluator gains, scores, task identities and domain labels are caller-supplied. Leave-one-out robustness does not prove evaluator independence or eliminate shared bias. Paired task metrics do not prove task representativeness, randomization or causal attribution. Domain scores are comparable only if upstream score scales and task definitions are genuinely comparable; this module cannot authenticate that. Hashes provide integrity linkage only, not trusted provenance or custody. No model execution, causal capability gain, RSI or ASI is demonstrated.

## Safety

Evidence/proposal-only. All execution flags remain false. No task execution, experiment, model change/training, HOLD release, merge or deployment is authorized.
