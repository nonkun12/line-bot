# AI Factory Stages 396–400: Final Evidence Readiness

## Scope
- **396 — Source declaration completeness:** unique evidence IDs with non-empty source references and source versions.
- **397 — Time-window validity:** integer timestamps, ordered windows, future-date rejection, and maximum evidence age.
- **398 — Evaluator separation declaration:** producer and evaluator labels must differ for each artifact.
- **399 — Decision consistency:** conflicting decisions for one evidence key block readiness.
- **400 — Final readiness:** requires PASS and a valid 64-character SHA-256 consistency seal for every upstream stage 386–395, with no missing, duplicate, or unexpected stages.

## Limitations and safety
All records and identities are caller-supplied declarations. Source references do not authenticate origin or truth; timestamps do not prove collection time; distinct evaluator labels do not prove organizational or technical independence; matching decisions do not establish correctness. SHA-256 is a deterministic consistency checksum, not a trusted signature or chain-of-custody proof.

The final result is proposal-only. `execution_authorized` and `promotion_authorized` are always false. A PASS is readiness of declared evidence only, not proof of model capability, RSI, or ASI. No experiments, training, model/weight changes, HOLD release, permission changes, production actions, merge, or deployment are performed.
