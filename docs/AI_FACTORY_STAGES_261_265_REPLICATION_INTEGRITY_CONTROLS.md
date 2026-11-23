# AI Factory Stages 261–265: Replication and Evaluation Integrity

This proposal-only extension adds checks for stratified coverage, environment parity, contamination-screen records, multiple comparisons, and independent replication.

## Stages

- **261 — Stratified coverage:** checks that every preregistered stratum meets its declared minimum task quota.
- **262 — Environment parity:** requires baseline and candidate manifests to match on runtime, hardware class, precision, sampling configuration, and resource budget declarations.
- **263 — Contamination screen:** requires a per-task screening evidence digest, a clear outcome declaration, and distinct evaluator/model-operator identifiers.
- **264 — Multiple comparisons:** applies a Bonferroni family-wise alpha allocation and recomputes conservative Hoeffding lower bounds for each estimate.
- **265 — Independent replication:** requires two integrity-checked evidence packages, distinct task-set digests, matching preregistered protocol parameters, distinct evaluator identifiers, and positive gates in both packages.

## Important limitations

- Strata, environment manifests, contamination outcomes, evidence digests, and evaluator identifiers are supplied by callers. These checks do not authenticate their origin or truth.
- Environment parity is equality of declared fields; it does not prove equal wall-clock conditions, energy use, hidden system prompts, data access, or operational isolation.
- A contamination-screen digest is not itself a contamination audit. Trusted task-bank custody and independent forensic review are still needed.
- Bonferroni correction is conservative and assumes the family of comparisons was fixed. This module does not prevent undisclosed analyses or post-hoc selection.
- Replication requires a distinct declared task-set digest and distinct evaluator identifier, but cannot prove institutional independence, absence of collusion, or genuinely held-out tasks.
- Stage265 compares protocol parameters while allowing the task-set digest to differ, which is necessary for replication on a distinct set.
- These are structural evidence gates, not proof of general intelligence, RSI, or ASI.

## Safety

Every stage fails closed unless HOLD is explicitly false. All task execution, experiment execution, model changes, merge/deploy, and HOLD-release authority flags remain false. No model execution, training, weight mutation, merge, deployment, or HOLD release is performed.
