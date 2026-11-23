# AI Factory Stages 326–330: Measurement Sensitivity

- **326 — Evaluator coalition ablation:** evaluates every declared evaluator-removal coalition up to a bounded size, not only single-evaluator leave-one-out.
- **327 — Task-difficulty strata:** requires every caller-declared difficulty stratum to meet paired-task coverage and gain floors.
- **328 — Gain-threshold sensitivity:** checks task-level positive share and mean gain across a declared threshold grid.
- **329 — Weight concentration:** bounds the maximum normalized task weight and enforces a weighted-gain floor.
- **330 — Integrated gate:** requires all four sealed checks and permits proposal eligibility for separate review only.

## Limitations

All evaluator gains, task scores, difficulty labels, thresholds and weights are caller-supplied. Coalition ablation does not establish evaluator independence. Difficulty strata are not authenticated. Threshold grids and weights may be selected opportunistically. The checks do not establish representative sampling, comparable score scales, causal attribution, or actual model capability gains. Digests provide integrity linkage only, not trusted provenance or custody. No RSI or ASI is demonstrated.

## Safety

Evidence/proposal-only. All execution flags remain false. No task execution, experiment, model change/training, HOLD release, merge or deployment is authorized.
