# AI Factory Stages 241–245 — Reproducibility and Robustness

All stages are deterministic evidence validators. They do not run experiments, alter models, or authorize execution.

- **241 — Reproducibility:** requires repeated runs with unique run IDs and identical artifact, protocol, dataset, suite, and environment identities. Primary-metric spread must fit an explicit tolerance.
- **242 — Stratified robustness:** requires declared slice coverage and a minimum gain threshold in every required stratum. Missing or regressing slices block support.
- **243 — Safety non-regression:** compares exact matching baseline/candidate safety metrics against explicit maximum degradation limits. Limits are metric-direction dependent and must be defined correctly by the caller.
- **244 — Gain attribution:** requires a declared randomized-controlled or matched-control design, distinct treatment/control groups, preregistration digest, independent evaluator identity, and positive effect estimate and lower confidence bound.
- **245 — Cycle evidence gate:** combines all four statuses into a separate-review recommendation only.

HOLD fails closed. Non-finite numbers, duplicate run/stratum IDs, mismatched evidence identities, missing slices, invalid digests, unsupported designs, evaluator mismatch, and safety regression are rejected or blocked.

Limitations:
- Matching run identifiers and digests do not prove the environment was honestly measured or execution was independent.
- Stratum robustness is only as complete as the caller's declared strata and sample design.
- Safety limits must reflect metric direction and clinically/operationally meaningful tolerances; this helper cannot choose them.
- Gain attribution remains conditional on randomization/matching integrity, no unmeasured confounding, protocol adherence, statistical assumptions, and evaluator validity.
- Passing these gates is not proof of recursive self-improvement, ASI, or general capability gain.
