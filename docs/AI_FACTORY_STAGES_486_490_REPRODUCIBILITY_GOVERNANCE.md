# AI Factory Stages 486–490: Reproducibility Governance

- **486 — Reproduction alignment:** require repeated runs to declare matching protocol, configuration, and dataset fingerprints.
- **487 — Repeated-run variance:** enforce a minimum run count and bounded score spread.
- **488 — Environment stability:** detect drift in declared runtime/environment fingerprints.
- **489 — Evaluator disagreement:** detect verdict conflicts and score/threshold contradictions.
- **490 — Integrated gate:** combine reproducibility, environment, evaluator, data-split, lineage, calibration, external-reference, and unresolved-HOLD checks.

## Safety and limitations
Fingerprints, run metadata, scores, evaluator IDs, and references are caller-supplied and unauthenticated. Matching strings do not prove identical execution or independent reruns; bounded score spread does not establish statistical reproducibility. The gate does not execute experiments, fetch external references, verify evidence provenance, or prove improvement. READY_FOR_REVIEW is not an authorization. HOLD release, execution, promotion, merge, and deployment remain unauthorized.
