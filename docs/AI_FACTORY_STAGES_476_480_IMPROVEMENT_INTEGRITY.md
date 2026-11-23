# AI Factory Stages 476–480: Improvement Integrity

- **476 — Protocol stability:** reject protocol, task-set, metric, or scoring-method drift across cycles.
- **477 — Score contract:** enforce finite score bounds and consistent optimization direction.
- **478 — Cycle completion:** reject interrupted or unrecognized cycle states.
- **479 — Evidence traceability:** require unique evidence references and SHA-256-shaped digests.
- **480 — Integrated gate:** combine longitudinal checks with protocol, score, completion, traceability, and unresolved-HOLD checks.

## Safety and limitations
All cycles, scores, references, digests, and evaluator identities are caller-supplied. Hash shape and unique references do not establish authenticity, provenance, completeness, or independent verification. A READY_FOR_REVIEW result is only a declaration-screen result; it does not prove sustained improvement or authorize clearing HOLD, execution, promotion, merge, or deployment. No experiments, training, model/weight changes, policy/permission changes, production actions, merge, or deployment.
