# AI Factory Stages 311–315: Sampling, Evaluator and Attrition Controls

- **311 — Inclusion probabilities:** validates positive bounded inclusion probabilities for the exact paired task IDs and records the declared sampling design.
- **312 — Evaluator assignment balance:** requires multiple declared evaluators, minimum task counts and a cap on any evaluator's share.
- **313 — Configuration scope:** requires invariant configuration digest parity and restricts declared changes to an explicit allowlist.
- **314 — Paired attrition:** compares baseline/candidate missing-task rates on the same declared task universe and enforces a maximum gap.
- **315 — Integrated gate:** requires all four sealed checks and yields proposal eligibility for separate review only.

## Limitations

All sampling probabilities, task identities, evaluator assignments, configuration digests, field names and presence labels are caller-supplied. Positive inclusion probabilities do not prove random sampling or correct probability calculation. Assignment balance does not establish evaluator independence, blinding or absence of collusion. Configuration digest parity does not authenticate configuration contents or prove runtime adherence. Attrition parity does not identify why tasks are missing or prove missingness is ignorable. Hashes provide integrity linkage only, not trusted provenance or custody. No model execution, causal capability gain, RSI or ASI is demonstrated.

## Safety

Evidence/proposal-only. All execution flags remain false. No task execution, experiment, model change/training, HOLD release, merge or deployment is authorized.
