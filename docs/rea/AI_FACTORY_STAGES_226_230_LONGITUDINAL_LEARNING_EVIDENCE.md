# AI Factory Stages 226–230 — Longitudinal Learning Evidence

All helpers are deterministic and proposal-only.

- **226 — Longitudinal ledger:** checks contiguous sequence numbers, unique event IDs, previous-digest links, and caller-reported signature verification. It does not prove immutable storage or perform cryptographic verification.
- **227 — Failure classification:** requires explicit known failure classes and produces a count profile.
- **228 — Hypothesis comparison:** ranks hypotheses only when suite, dataset, environment, and design identifiers match; eligibility requires positive gain lower bound, safety ≥0.95, and cost ratio ≤1.10. The ranking is descriptive, not causal.
- **229 — Evaluation bias risk:** screens for configured evaluation-rate gaps and low stratum coverage. No flags do not prove absence of bias.
- **230 — Improvement candidates:** converts validated failure and bias evidence into suggested investigation actions only.

HOLD fails closed. No task execution, experiment execution, training, model mutation, rollback, merge, deployment, or authorization is performed. Signature flags and provenance are caller-supplied and must be independently verified by the surrounding system. These stages do not establish RSI or ASI, nor demonstrate an actual capability gain.
