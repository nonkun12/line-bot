# AI Factory Stages 306–310: Stratified Evidence Quality and Freshness

- **306 — Stratum balance:** requires matching declared strata, minimum counts per stratum, and bounded baseline/candidate mix shift.
- **307 — Scoring-rubric parity:** requires exact version and content-digest parity between preregistered and observed rubric declarations.
- **308 — Evidence freshness:** validates timezone-aware timestamps, rejects future-dated evidence, and enforces a maximum evidence age.
- **309 — Domain-level missingness:** checks missingness rates independently for each declared domain and enforces minimum per-domain sample totals.
- **310 — Integrated gate:** requires all four sealed checks and yields proposal eligibility for separate independent review only.

## Limitations

All counts, labels, rubric versions/digests and timestamps are caller-supplied. Stratum balance does not prove representative sampling or randomized assignment. Rubric digest parity does not authenticate the rubric source or prove evaluator adherence. Timestamp syntax and age checks do not establish trusted time or custody. Domain missingness rates do not identify the missingness mechanism. Hash-sealed outputs provide integrity linkage only, not independent provenance. No causal improvement, recursive self-improvement (RSI), or ASI is demonstrated.

## Safety

Evidence/proposal-only. All execution flags remain false. No task execution, experiment, model change/training, HOLD release, merge or deployment is authorized.
