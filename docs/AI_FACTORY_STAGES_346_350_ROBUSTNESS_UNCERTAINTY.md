# AI Factory Stages 346–350 — Robustness and uncertainty gates

- 346 paired reference/perturbed score stability (caller-supplied observations only).
- 347 explicit missing-evidence share bound; no missing-at-random assumption.
- 348 bounded interval width / declared precision.
- 349 exact metric direction and unit contract.
- 350 sealed integration gate; fail-closed and proposal-only.

All values, case pairing, intervals, counts and metric definitions are caller-supplied and unauthenticated. This does not execute perturbations, establish statistical coverage, rule out missingness bias, validate metric semantics, or demonstrate RSI/ASI. All execution, model-change, merge/deploy and HOLD-release flags remain false.
