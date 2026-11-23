# AI Factory Stages 436–440: Release Readiness

- **436 — Artifact inventory:** unique artifact IDs, versions, kinds, and SHA-256-shaped digests.
- **437 — Required validations:** exactly one successful result per required check, with consistent declared HEAD SHA.
- **438 — Blocker register:** unresolved blockers or missing resolution references block readiness.
- **439 — Rollback readiness:** documented owner, trigger, steps, verification method, evidence reference, and tested declaration.
- **440 — Aggregate gate:** candidate readiness report tied to an expected HEAD SHA.

## Safety and limitations
All evidence is caller-supplied. Hash shape does not authenticate artifacts; check names/statuses do not prove that CI ran in a trusted environment; a "tested" rollback declaration is not independently verified. READY_FOR_SEPARATE_REVIEW is not release approval. The gate never authorizes release, execution, or promotion and performs no deployment. No HOLD release, experiments, training, model/weight changes, permission changes, production actions, merge, or deployment. No RSI/ASI claim.
