# AI Factory Stages 221-225 — Experiment Governance

All stages are deterministic proposal-only helpers. They do not run experiments or change models.

- 221 ranks evidence-complete, safety-approved experiment candidates by declared expected information gain per estimated cost.
- 222 reports observed gain per actual cost and budget overrun.
- 223 checks signed evidence across repeated windows for positive gain and a 0.95 safety floor.
- 224 detects quality/safety regressions against an explicit baseline and tolerances; it does not authorize rollback.
- 225 requires distinct executor/evaluator identifiers and a verified evaluation signature.

Limitations: candidate gain and cost estimates are caller-supplied; ranking quality depends on them. Distinct identities do not prove organizational or methodological independence. Window signatures must be independently verified by the caller. Sampling bias, metric validity, power, and causal attribution remain external assumptions. HOLD fails closed. No execution, model change, rollback, merge, or deployment is authorized.
