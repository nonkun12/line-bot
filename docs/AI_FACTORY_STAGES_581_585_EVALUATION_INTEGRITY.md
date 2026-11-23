# AI Factory Stages 581–585: Evaluation Integrity

- 581: evaluator, evaluation-run and evaluated-subject provenance
- 582: rubric and result artifact references
- 583: timestamped, typed metric-result validation
- 584: evaluator independence, conflicts and limitations declarations
- 585: integrated fail-closed evaluation-integrity gate

The validator checks declarations and basic value shape only. It does not fetch or hash artifacts, authenticate evaluators, reproduce results, or establish that metrics are truthful. Complete declarations remain REVIEW_REQUIRED; acceptance, model changes and production changes are never authorized.
