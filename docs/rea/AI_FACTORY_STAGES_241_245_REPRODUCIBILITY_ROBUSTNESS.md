# AI Factory Stages 241–245 — Reproducibility and Robustness

All stages are deterministic evidence validators. They do not run experiments, alter models, or authorize execution.

- **241 — Reproducibility:** requires at least three runs with unique run IDs and unique caller-supplied run digests, identical artifact/protocol/dataset/suite/environment identities, and bounded primary-metric spread.
- **242 — Stratified robustness:** requires complete coverage of every declared stratum, a strictly positive minimum gain, and at least two samples per stratum. Partial coverage cannot pass.
- **243 — Safety non-regression:** each metric must explicitly declare `direction` (`higher` or `lower`) and `max_degradation`. Unknown directions fail closed.
- **244 — Gain attribution:** requires a randomized or matched assignment method, distinct treatment/control groups, a valid preregistration digest, distinct proposer/runner/evaluator identities, an assignment method matching the design type, a preregistration digest equal to the evaluated protocol digest, and an ordered positive lower confidence bound.
- **245 — Cycle evidence gate:** validates result digests, proposal-only/no-authority flags, expected statuses, and a common experiment identity before recommending separate review.

HOLD must be explicitly false; missing, malformed, or unknown values fail closed.

Limitations:
- Run digests and result digests are unkeyed integrity checks, not signatures or proof of independent execution. A malicious caller can recompute them.
- Identity strings and role identifiers are caller-supplied and do not prove real-world independence.
- Stratum completeness is relative to the caller-declared required strata; the helper cannot prove that the declared population is complete.
- Safety thresholds and metric directions require domain-specific validation.
- Gain attribution remains conditional on randomization/matching integrity, no unmeasured confounding, protocol adherence, statistical assumptions, and evaluator validity.
- Passing these gates is not proof of recursive self-improvement, ASI, or general capability gain.
