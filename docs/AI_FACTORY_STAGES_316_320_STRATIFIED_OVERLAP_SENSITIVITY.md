# AI Factory Stages 316–320: Stratified, Overlap and Sensitivity Controls

- **316 — Stratified sampling:** validates exact task-to-stratum coverage, minimum observations per stratum and bounded positive inclusion probabilities.
- **317 — Evaluator overlap:** reports pairwise shared-task counts and Jaccard overlap against declared bounds.
- **318 — Evaluator/domain coverage:** requires every declared domain to be covered by a minimum number of evaluators and observations.
- **319 — Attrition sensitivity:** computes conservative candidate-minus-baseline score bounds by assigning missing outcomes the declared score minimum/maximum.
- **320 — Integrated gate:** requires all four sealed checks and yields proposal eligibility for separate review only.

## Limitations

All task strata, probabilities, evaluator assignments, domain counts, score bounds and missingness counts are caller-supplied. These checks do not authenticate sampling frames, verify random selection, establish evaluator independence/blinding, prove domain representativeness, or identify the missingness mechanism. Worst-case bounds are only as defensible as the declared score range and paired universe. Hashes provide integrity linkage, not trusted provenance or custody. No causal capability gain, RSI or ASI is demonstrated.

## Safety

Evidence/proposal-only. All execution flags remain false. No task execution, experiment, model change/training, HOLD release, merge or deployment is authorized.
