# AI Factory Stages 216-220 — Evidence Quality and Prioritization

Proposal-only deterministic helpers. No execution, training, feedback mutation, model activation, merge, or deployment authorization.

- Stage 216: validate aggregate success/safety counts against raw classifications.
- Stage 217: Wilson score interval for a binomial success rate; interval is descriptive and assumes the observations fit the model.
- Stage 218: required-stratum coverage and missing/unexpected stratum inventory.
- Stage 219: conservative heuristic ranking score; not inferential or causal evidence.
- Stage 220: recommends next evaluation step in fail-closed order (integrity, coverage, safety, uncertainty).

Limitations: caller must authenticate evidence and establish sampling/design quality. Wilson interval assumptions, selection bias, dependence, multiplicity, evaluator trust, and power are not resolved by these utilities. HOLD always blocks. Recommendations are not execution permission.
