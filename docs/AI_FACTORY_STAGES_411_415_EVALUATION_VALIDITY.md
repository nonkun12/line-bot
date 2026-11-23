# AI Factory Stages 411–415: Evaluation Input Validity

## Scope
- **411 — Metric specifications:** unique metric IDs, definitions, units, direction, and aggregation declarations.
- **412 — Denominator integrity:** non-negative integer counts, positive denominators, numerator bounds, and sample-count coverage.
- **413 — Uncertainty interval structure:** finite ordered lower/point/upper values and a declared method label.
- **414 — Comparison compatibility:** matching declared protocol, population, and evaluation window for baseline/candidate comparisons.
- **415 — Aggregate gate:** fail-closed combination of the four validators and registration checks.

## Safety and limitations
These checks validate input structure and arithmetic, not scientific validity. A declared interval method is not recomputed or verified; bounds do not establish statistical coverage, calibration, significance, causal attribution, or sufficient sample size. Matching labels do not prove that populations or protocols were actually equivalent. Caller-supplied metric definitions and counts are not independently authenticated.

The aggregate is proposal-only. `execution_authorized` and `promotion_authorized` are always false. No experiments, training, model/weight changes, HOLD release, permission changes, production actions, merge, or deployment are performed. No RSI/ASI claim is made.
