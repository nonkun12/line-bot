# AI Factory Stages 446–450: Capability Evaluation Controls

- **446 — Evaluation protocol:** versioned objective, task set, scoring method, owner, unique task IDs, and numeric score bounds.
- **447 — Result coverage:** one bounded, referenced score per expected task, with no missing or unexpected tasks.
- **448 — Baseline alignment:** protocol, task set, scoring method, and score bounds must match.
- **449 — Regression threshold:** flag a current score drop beyond the declared absolute tolerance.
- **450 — Aggregate scorecard:** sealed, fail-closed evaluation readiness record.

## Safety and limitations
Scores, references, protocol declarations, and baseline values are caller-supplied and not independently verified. A numeric score is meaningful only within its declared task set and scoring method. A matched baseline does not establish broad generalization, independence, or scientific validity. The aggregate is not an intelligence/ASI assessment and does not authorize capability claims, execution, or promotion. No model/weight changes, training, experiments, policy changes, permission changes, production actions, merge, or deployment.
