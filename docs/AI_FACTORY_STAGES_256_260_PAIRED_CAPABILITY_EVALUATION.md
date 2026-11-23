# AI Factory Stages 256–260: Paired Capability Evaluation

This proposal-only module evaluates already-recorded baseline/candidate outputs on a preregistered task set. It does not invoke models, train weights, mutate deployments, or authorize experiments.

## Stages

- **256 — Preregistration:** freezes metric, direction, minimum practically relevant gain, confidence parameter, minimum sample size (at least 30 pairs), and task-set digest.
- **257 — Paired result validation:** requires one unique baseline/candidate score pair per task, finite scores in [0,1], valid task digests, exact task-set identity, and a minimum number of pairs.
- **258 — Gain estimation:** computes direction-adjusted paired differences and a two-sided Hoeffding interval. Since each paired difference lies in [-1,1], the conservative radius is sqrt(2 * ln(2/alpha) / n).
- **259 — Evidence gate:** supports a gain only when the lower confidence bound is strictly greater than the preregistered minimum gain.
- **260 — Evidence package:** verifies result digests and cross-stage protocol/data linkage, then packages the result for independent replication review.

## Interpretation and limitations

- The confidence interval is distribution-free but often very conservative; it is not a substitute for a fully specified statistical analysis plan.
- The module validates supplied scores and task digests; it cannot prove that scores were honestly generated, that task prompts were hidden, or that baseline/candidate systems were run under equivalent compute, sampling, or environment conditions.
- Task-set digest proves byte-level identity of the declared identifiers/digests, not task quality or independence.
- The current interface accepts bounded scalar scores. It does not implement stratification, multiple-comparison correction, adaptive stopping, missing-data handling, evaluator calibration, or contamination detection.
- Preregistration is represented by a digest, not a trusted timestamped registry; callers could construct a new protocol after observing results. Independent timestamped protocol custody is required to establish precommitment.
- A positive lower bound above a practical threshold is evidence on this task set, not proof of general intelligence, recursive self-improvement, or ASI.
- Independent replication on a separately controlled, held-out task set is required before interpreting the result as robust capability improvement.
- Every stage fails closed when HOLD is not explicitly false. All execution, experiment, model-change, merge/deploy, and HOLD-release authority flags remain false.

## Next required controls

Add an independently administered task bank, blind evaluator, trusted timestamped preregistration registry, environment/resource parity attestations, contamination checks, and replicated multi-domain evaluation. Keep model changes and deployment outside this evidence pipeline.
